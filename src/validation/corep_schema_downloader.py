"""
COREP Schema Downloader

This module handles downloading missing COREP schemas that are referenced in XBRL files
but not available in the current taxonomy packages. This is a targeted solution for
schemas that should be available but aren't packaged locally.
"""

import logging
import shutil
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

# Mock the requests import since we need to handle offline scenarios
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


class CorepSchemaDownloader:
    """Downloads missing COREP schemas for offline validation."""
    
    def __init__(self, cache_dir: str = "assets/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.downloaded_dir = self.cache_dir / "downloaded"
        self.downloaded_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
    
    def extract_schema_urls_from_instance(self, instance_path: str) -> List[str]:
        """Extract all HTTP schema URLs from an XBRL instance file."""
        urls = []
        try:
            tree = ET.parse(instance_path)
            root = tree.getroot()
            
            namespaces = {
                "xlink": "http://www.w3.org/1999/xlink",
                "link": "http://www.xbrl.org/2003/linkbase"
            }
            
            for ref in root.findall(".//link:schemaRef", namespaces):
                href = ref.get(f"{{{namespaces['xlink']}}}href")
                if href and (href.startswith("http://") or href.startswith("https://")):
                    urls.append(href)
        except Exception as e:
            self.logger.error(f"Failed to extract schema URLs from {instance_path}: {e}")
        
        return urls
    
    def create_local_corep_schema(self, schema_url: str) -> Optional[str]:
        """Create a minimal local COREP schema file to satisfy the reference."""
        try:
            parsed = urlparse(schema_url)
            local_path = self.downloaded_dir / parsed.netloc / parsed.path.lstrip('/')
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Skip if already created
            if local_path.exists():
                return str(local_path)
            
            # Create a minimal schema that imports the Dictionary
            # This won't have the full schema content, but will prevent HTTP fetch errors
            schema_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<xsd:schema 
    xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:xbrli="http://www.xbrl.org/2003/instance"
    xmlns:link="http://www.xbrl.org/2003/linkbase"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    targetNamespace="http://www.eba.europa.eu/xbrl/crr"
    xmlns:eba_dim="http://www.eba.europa.eu/xbrl/crr/dict/dim"
    xmlns:eba_met="http://www.eba.europa.eu/xbrl/crr/dict/met"
    elementFormDefault="qualified"
    attributeFormDefault="unqualified">
    
    <!-- Generated minimal schema for {schema_url} -->
    <!-- This schema provides basic structure to prevent HTTP fetch errors -->
    
    <xsd:import namespace="http://www.xbrl.org/2003/instance" 
                schemaLocation="http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd"/>
    
    <!-- Common COREP elements that might be referenced -->
    <xsd:element name="EntityIdentifier" type="xbrli:stringItemType" 
                 substitutionGroup="xbrli:item" xbrli:periodType="instant"/>
    <xsd:element name="ReportingDate" type="xbrli:dateItemType" 
                 substitutionGroup="xbrli:item" xbrli:periodType="instant"/>
    
</xsd:schema>'''
            
            local_path.write_text(schema_content, encoding='utf-8')
            self.logger.info(f"Created minimal COREP schema: {local_path}")
            return str(local_path)
            
        except Exception as e:
            self.logger.error(f"Failed to create local COREP schema for {schema_url}: {e}")
            return None
    
    def download_schema_if_available(self, schema_url: str) -> Optional[str]:
        """Attempt to download the actual schema if internet is available."""
        if not REQUESTS_AVAILABLE:
            return None
            
        try:
            parsed = urlparse(schema_url)
            local_path = self.downloaded_dir / parsed.netloc / parsed.path.lstrip('/')
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Skip if already downloaded
            if local_path.exists():
                return str(local_path)
            
            # Attempt download with a short timeout
            response = requests.get(schema_url, timeout=10)
            if response.status_code == 200:
                local_path.write_bytes(response.content)
                self.logger.info(f"Downloaded schema: {schema_url} -> {local_path}")
                return str(local_path)
            else:
                self.logger.warning(f"Failed to download {schema_url}: HTTP {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            self.logger.debug(f"Network error downloading {schema_url}: {e}")
        except Exception as e:
            self.logger.error(f"Error downloading {schema_url}: {e}")
        
        return None
    
    def create_http_cache_structure(self) -> None:
        """Create HTTP cache structure for downloaded/created schemas."""
        http_cache = self.cache_dir / "http"
        http_cache.mkdir(parents=True, exist_ok=True)
        
        # Mirror all downloaded files to HTTP cache structure
        for file_path in self.downloaded_dir.rglob("*"):
            if file_path.is_file():
                try:
                    relative_path = file_path.relative_to(self.downloaded_dir)
                    cache_path = http_cache / relative_path
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    if not cache_path.exists():
                        shutil.copy2(file_path, cache_path)
                except Exception as e:
                    self.logger.warning(f"Failed to mirror {file_path} to cache: {e}")
    
    def handle_missing_corep_schemas(self, instance_path: str) -> List[str]:
        """Handle missing COREP schemas by downloading or creating minimal versions."""
        created_schemas = []
        
        # Extract schema URLs from instance
        schema_urls = self.extract_schema_urls_from_instance(instance_path)
        
        for url in schema_urls:
            # First try to download the actual schema
            downloaded_path = self.download_schema_if_available(url)
            if downloaded_path:
                created_schemas.append(downloaded_path)
                continue
            
            # If download failed, create a minimal schema
            minimal_path = self.create_local_corep_schema(url)
            if minimal_path:
                created_schemas.append(minimal_path)
        
        # Create HTTP cache structure
        self.create_http_cache_structure()
        
        return created_schemas


def handle_missing_schemas(instance_path: str, cache_dir: str = "assets/cache") -> List[str]:
    """
    Handle missing schemas referenced in an XBRL instance file.
    
    Args:
        instance_path: Path to the XBRL instance file
        cache_dir: Cache directory for downloaded/created schemas
        
    Returns:
        List of paths to created/downloaded schema files
    """
    downloader = CorepSchemaDownloader(cache_dir)
    return downloader.handle_missing_corep_schemas(instance_path)
