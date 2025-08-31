"""
Schema Localization Module

This module handles the localization of HTTP schema references to local files
from taxonomy packages, preventing HTTP fetch attempts during offline validation.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse
from xml.etree import ElementTree as ET


class SchemaLocalizer:
    """Handles mapping of HTTP schema URLs to local files from taxonomy packages."""
    
    def __init__(self, cache_dir: str = "assets/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.extraction_base = self.cache_dir / "extracted"
        self.extraction_base.mkdir(parents=True, exist_ok=True)
        self.catalog_file = self.cache_dir / "catalog.xml"
        
        # Mapping of HTTP URLs to local file paths
        self.url_to_local: Dict[str, str] = {}
        self.logger = logging.getLogger(__name__)
    
    def extract_all_packages(self, package_paths: List[str]) -> None:
        """Extract all taxonomy packages to local directories."""
        for package_path in package_paths:
            if package_path.endswith('.zip') and Path(package_path).exists():
                self._extract_package(package_path)
    
    def _extract_package(self, package_path: str) -> None:
        """Extract a single taxonomy package."""
        package_path_obj = Path(package_path)
        package_name = package_path_obj.stem
        extract_dir = self.extraction_base / package_name
        
        # Skip if already extracted
        if extract_dir.exists():
            return
            
        extract_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            with zipfile.ZipFile(package_path, 'r') as zf:
                # Extract all files
                zf.extractall(extract_dir)
                self.logger.info(f"Extracted package: {package_path} to {extract_dir}")
                
                # Build URL mappings from extracted content
                self._build_url_mappings(extract_dir)
                
        except Exception as e:
            self.logger.error(f"Failed to extract package {package_path}: {e}")
    
    def _build_url_mappings(self, extract_dir: Path) -> None:
        """Build mappings from HTTP URLs to local file paths."""
        # Look for files under www.eba.europa.eu structure
        eba_base = extract_dir / "www.eba.europa.eu"
        if not eba_base.exists():
            # Try with package wrapper
            for child in extract_dir.iterdir():
                if child.is_dir():
                    potential_eba = child / "www.eba.europa.eu"
                    if potential_eba.exists():
                        eba_base = potential_eba
                        break
        
        if eba_base.exists():
            # Walk through all files and create HTTP URL mappings
            for file_path in eba_base.rglob("*"):
                if file_path.is_file():
                    relative_path = file_path.relative_to(eba_base.parent)
                    http_url = f"http://{relative_path.as_posix()}"
                    https_url = f"https://{relative_path.as_posix()}"
                    
                    local_path = str(file_path.absolute())
                    self.url_to_local[http_url] = local_path
                    self.url_to_local[https_url] = local_path
    
    def create_catalog_file(self) -> str:
        """Create an XML catalog file for Arelle to use for URL remapping."""
        catalog_content = '''<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog" prefer="system">
'''
        
        # Add URI mappings
        for http_url, local_path in self.url_to_local.items():
            local_uri = Path(local_path).as_uri()
            catalog_content += f'    <uri name="{http_url}" uri="{local_uri}"/>\n'
        
        catalog_content += '</catalog>\n'
        
        # Write catalog file
        self.catalog_file.write_text(catalog_content, encoding='utf-8')
        return str(self.catalog_file)
    
    def create_http_cache_mirror(self) -> None:
        """Create HTTP cache mirror structure for Arelle's web cache."""
        http_cache = self.cache_dir / "http"
        http_cache.mkdir(parents=True, exist_ok=True)
        
        for http_url, local_path in self.url_to_local.items():
            if http_url.startswith("http://"):
                # Remove http:// prefix
                relative_url = http_url[7:]
                cache_path = http_cache / relative_url
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                
                try:
                    if not cache_path.exists():
                        shutil.copy2(local_path, cache_path)
                except Exception as e:
                    self.logger.warning(f"Failed to mirror {local_path} to {cache_path}: {e}")
    
    def localize_instance_file(self, instance_path: str) -> str:
        """
        Create a localized copy of an XBRL instance file with HTTP schemaRefs 
        replaced by local file URIs.
        """
        try:
            # Parse the XML
            tree = ET.parse(instance_path)
            root = tree.getroot()
            
            # Define namespaces
            namespaces = {
                "xlink": "http://www.w3.org/1999/xlink",
                "link": "http://www.xbrl.org/2003/linkbase"
            }
            
            # Find all schemaRef elements
            schema_refs = root.findall(".//link:schemaRef", namespaces)
            modified = False
            
            for ref in schema_refs:
                href = ref.get(f"{{{namespaces['xlink']}}}href")
                if href and (href.startswith("http://") or href.startswith("https://")):
                    # Check if we have a local mapping
                    if href in self.url_to_local:
                        local_path = self.url_to_local[href]
                        local_uri = Path(local_path).as_uri()
                        ref.set(f"{{{namespaces['xlink']}}}href", local_uri)
                        modified = True
                        self.logger.info(f"Localized schemaRef: {href} -> {local_uri}")
                    else:
                        self.logger.warning(f"No local mapping found for: {href}")
            
            if modified:
                # Create localized version
                localized_dir = self.cache_dir / "localized"
                localized_dir.mkdir(parents=True, exist_ok=True)
                
                instance_name = Path(instance_path).name
                localized_path = localized_dir / f"localized_{instance_name}"
                
                # Write the modified XML
                tree.write(localized_path, encoding="utf-8", xml_declaration=True)
                return str(localized_path)
            
        except Exception as e:
            self.logger.error(f"Failed to localize instance file {instance_path}: {e}")
        
        return instance_path
    
    def get_mapping_statistics(self) -> Dict[str, int]:
        """Get statistics about URL mappings."""
        return {
            "total_mappings": len(self.url_to_local),
            "http_mappings": len([url for url in self.url_to_local if url.startswith("http://")]),
            "https_mappings": len([url for url in self.url_to_local if url.startswith("https://")]),
        }


def create_comprehensive_localization(
    package_paths: List[str],
    instance_path: str,
    cache_dir: str = "assets/cache"
) -> Tuple[str, str, Dict[str, int]]:
    """
    Create comprehensive schema localization for offline validation.
    
    Returns:
        - Path to localized instance file
        - Path to catalog file for Arelle
        - Statistics about mappings created
    """
    localizer = SchemaLocalizer(cache_dir)
    
    # Extract all packages and build mappings
    localizer.extract_all_packages(package_paths)
    
    # Create HTTP cache mirror for Arelle
    localizer.create_http_cache_mirror()
    
    # Create XML catalog file
    catalog_path = localizer.create_catalog_file()
    
    # Localize the instance file
    localized_instance = localizer.localize_instance_file(instance_path)
    
    # Get statistics
    stats = localizer.get_mapping_statistics()
    
    return localized_instance, catalog_path, stats


def download_missing_schemas(
    missing_urls: List[str],
    cache_dir: str = "assets/cache"
) -> List[str]:
    """
    Attempt to download missing schemas that are not in taxonomy packages.
    This is a fallback for schemas that should be available but aren't packaged.
    
    Note: This requires internet access and should only be used as a last resort
    to populate the local cache for future offline use.
    """
    import requests
    from time import sleep
    
    cache_path = Path(cache_dir) / "downloaded"
    cache_path.mkdir(parents=True, exist_ok=True)
    
    successfully_downloaded = []
    
    for url in missing_urls:
        try:
            # Parse URL to create local path
            parsed = urlparse(url)
            local_path = cache_path / parsed.netloc / parsed.path.lstrip('/')
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Skip if already downloaded
            if local_path.exists():
                successfully_downloaded.append(str(local_path))
                continue
            
            # Download with retry logic
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                local_path.write_bytes(response.content)
                successfully_downloaded.append(str(local_path))
                logging.info(f"Downloaded: {url} -> {local_path}")
            else:
                logging.warning(f"Failed to download {url}: HTTP {response.status_code}")
            
            # Rate limiting
            sleep(0.5)
            
        except Exception as e:
            logging.error(f"Error downloading {url}: {e}")
    
    return successfully_downloaded
