#!/usr/bin/env python3
"""
Automated diff framework to compare our XBRL validation outputs vs Altova outputs.
Supports multiple input formats and provides detailed analysis.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class ValidationMessage:
    """Normalized validation message for comparison."""
    level: str
    code: str
    message: str
    file_path: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    element: Optional[str] = None
    
    def __post_init__(self):
        # Normalize level
        self.level = self.level.upper() if self.level else "UNKNOWN"
        # Normalize code
        self.code = self.code.strip() if self.code else ""
        # Normalize message (remove extra whitespace)
        self.message = " ".join(self.message.split()) if self.message else ""
    
    def similarity_key(self) -> str:
        """Key for matching similar messages across tools."""
        return f"{self.level}|{self.code}|{self.message[:100]}"
    
    def __str__(self) -> str:
        location = ""
        if self.file_path:
            location = f" @ {Path(self.file_path).name}"
        if self.line:
            location += f":{self.line}"
        return f"[{self.level}] {self.code}: {self.message[:80]}{location}"


class ValidationResultLoader:
    """Load validation results from different formats."""
    
    @staticmethod
    def load_our_csv(csv_path: str) -> List[ValidationMessage]:
        """Load our validation_messages.csv format."""
        messages = []
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    msg = ValidationMessage(
                        level=row.get('level', ''),
                        code=row.get('code', ''),
                        message=row.get('message', ''),
                        file_path=row.get('docUri', ''),
                        line=int(row['line']) if row.get('line') and row['line'].isdigit() else None,
                        column=int(row['col']) if row.get('col') and row['col'].isdigit() else None,
                        element=row.get('modelObjectQname', '')
                    )
                    messages.append(msg)
        except Exception as e:
            print(f"❌ Error loading our CSV {csv_path}: {e}")
        return messages
    
    @staticmethod
    def load_altova_csv(csv_path: str) -> List[ValidationMessage]:
        """Load Altova CSV format (assumed structure)."""
        messages = []
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Try common Altova column names
                    level = (row.get('Severity') or row.get('Level') or 
                            row.get('Type') or row.get('severity') or '').upper()
                    code = (row.get('Code') or row.get('ErrorCode') or 
                           row.get('MessageCode') or row.get('code') or '')
                    message = (row.get('Message') or row.get('Description') or 
                              row.get('Text') or row.get('message') or '')
                    file_path = (row.get('File') or row.get('Document') or 
                                row.get('Uri') or row.get('file') or '')
                    
                    msg = ValidationMessage(
                        level=level,
                        code=code,
                        message=message,
                        file_path=file_path,
                        line=int(row['Line']) if row.get('Line') and str(row['Line']).isdigit() else None,
                        column=int(row['Column']) if row.get('Column') and str(row['Column']).isdigit() else None,
                        element=row.get('Element') or row.get('QName') or ''
                    )
                    messages.append(msg)
        except Exception as e:
            print(f"❌ Error loading Altova CSV {csv_path}: {e}")
        return messages
    
    @staticmethod
    def load_altova_json(json_path: str) -> List[ValidationMessage]:
        """Load Altova JSON format (assumed structure)."""
        messages = []
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Handle different JSON structures
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get('messages', data.get('results', data.get('errors', [])))
            else:
                items = []
            
            for item in items:
                if not isinstance(item, dict):
                    continue
                    
                msg = ValidationMessage(
                    level=str(item.get('severity', item.get('level', item.get('type', '')))).upper(),
                    code=str(item.get('code', item.get('errorCode', ''))),
                    message=str(item.get('message', item.get('description', item.get('text', '')))),
                    file_path=str(item.get('file', item.get('document', item.get('uri', '')))),
                    line=item.get('line'),
                    column=item.get('column'),
                    element=str(item.get('element', item.get('qname', '')))
                )
                messages.append(msg)
        except Exception as e:
            print(f"❌ Error loading Altova JSON {json_path}: {e}")
        return messages


class ValidationDiff:
    """Compare validation results between tools."""
    
    def __init__(self, our_messages: List[ValidationMessage], altova_messages: List[ValidationMessage]):
        self.our_messages = our_messages
        self.altova_messages = altova_messages
        
        # Build indices for efficient comparison
        self.our_by_key = {msg.similarity_key(): msg for msg in our_messages}
        self.altova_by_key = {msg.similarity_key(): msg for msg in altova_messages}
        
        self.our_keys = set(self.our_by_key.keys())
        self.altova_keys = set(self.altova_by_key.keys())
    
    def analyze(self) -> Dict[str, Any]:
        """Perform comprehensive diff analysis."""
        
        # Basic counts
        analysis = {
            "our_total": len(self.our_messages),
            "altova_total": len(self.altova_messages),
            "common_messages": len(self.our_keys & self.altova_keys),
            "our_unique": len(self.our_keys - self.altova_keys),
            "altova_unique": len(self.altova_keys - self.our_keys),
        }
        
        # Severity breakdown
        our_by_level = defaultdict(int)
        altova_by_level = defaultdict(int)
        
        for msg in self.our_messages:
            our_by_level[msg.level] += 1
        for msg in self.altova_messages:
            altova_by_level[msg.level] += 1
        
        analysis["our_by_level"] = dict(our_by_level)
        analysis["altova_by_level"] = dict(altova_by_level)
        
        # Code breakdown
        our_by_code = defaultdict(int)
        altova_by_code = defaultdict(int)
        
        for msg in self.our_messages:
            our_by_code[msg.code] += 1
        for msg in self.altova_messages:
            altova_by_code[msg.code] += 1
        
        analysis["our_top_codes"] = dict(sorted(our_by_code.items(), key=lambda x: x[1], reverse=True)[:10])
        analysis["altova_top_codes"] = dict(sorted(altova_by_code.items(), key=lambda x: x[1], reverse=True)[:10])
        
        # Calculate similarity score
        if analysis["our_total"] + analysis["altova_total"] > 0:
            similarity = (2 * analysis["common_messages"]) / (analysis["our_total"] + analysis["altova_total"])
        else:
            similarity = 1.0
        analysis["similarity_score"] = similarity
        
        return analysis
    
    def get_unique_messages(self, ours_only: bool = True) -> List[ValidationMessage]:
        """Get messages unique to one tool."""
        if ours_only:
            unique_keys = self.our_keys - self.altova_keys
            return [self.our_by_key[key] for key in unique_keys]
        else:
            unique_keys = self.altova_keys - self.our_keys
            return [self.altova_by_key[key] for key in unique_keys]


def print_analysis(analysis: Dict[str, Any]) -> None:
    """Print formatted analysis results."""
    print("\n" + "="*80)
    print("XBRL VALIDATION COMPARISON: OUR TOOL vs ALTOVA")
    print("="*80)
    
    print(f"\n📊 MESSAGE COUNTS:")
    print(f"  Our tool:     {analysis['our_total']:,} messages")
    print(f"  Altova:       {analysis['altova_total']:,} messages")
    print(f"  Common:       {analysis['common_messages']:,} messages")
    print(f"  Our unique:   {analysis['our_unique']:,} messages")
    print(f"  Altova unique: {analysis['altova_unique']:,} messages")
    
    print(f"\n🎯 SIMILARITY SCORE: {analysis['similarity_score']:.1%}")
    if analysis['similarity_score'] > 0.9:
        print("  ✅ EXCELLENT - Very high agreement")
    elif analysis['similarity_score'] > 0.7:
        print("  ✅ GOOD - High agreement with some differences")
    elif analysis['similarity_score'] > 0.5:
        print("  ⚠️  MODERATE - Significant differences present")
    else:
        print("  ❌ LOW - Major differences, investigation needed")
    
    print(f"\n⚠️  SEVERITY BREAKDOWN:")
    print("  Our tool:")
    for level, count in sorted(analysis['our_by_level'].items()):
        print(f"    {level}: {count:,}")
    print("  Altova:")
    for level, count in sorted(analysis['altova_by_level'].items()):
        print(f"    {level}: {count:,}")
    
    print(f"\n🔍 TOP ERROR CODES:")
    print("  Our tool:")
    for code, count in list(analysis['our_top_codes'].items())[:5]:
        print(f"    {code}: {count:,}")
    print("  Altova:")
    for code, count in list(analysis['altova_top_codes'].items())[:5]:
        print(f"    {code}: {count:,}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare XBRL validation outputs")
    parser.add_argument("--our-csv", required=True, help="Path to our validation_messages.csv")
    parser.add_argument("--altova-csv", help="Path to Altova CSV output")
    parser.add_argument("--altova-json", help="Path to Altova JSON output")
    parser.add_argument("--show-unique", action="store_true", help="Show unique messages from each tool")
    parser.add_argument("--max-unique", type=int, default=20, help="Max unique messages to show")
    parser.add_argument("--output-json", help="Write detailed analysis to JSON file")
    
    args = parser.parse_args()
    
    if not args.altova_csv and not args.altova_json:
        print("❌ Error: Must provide either --altova-csv or --altova-json")
        return 1
    
    # Load our results
    print(f"Loading our results from {args.our_csv}...")
    our_messages = ValidationResultLoader.load_our_csv(args.our_csv)
    print(f"✅ Loaded {len(our_messages)} messages from our tool")
    
    # Load Altova results
    altova_messages = []
    if args.altova_csv:
        print(f"Loading Altova results from {args.altova_csv}...")
        altova_messages = ValidationResultLoader.load_altova_csv(args.altova_csv)
    elif args.altova_json:
        print(f"Loading Altova results from {args.altova_json}...")
        altova_messages = ValidationResultLoader.load_altova_json(args.altova_json)
    
    print(f"✅ Loaded {len(altova_messages)} messages from Altova")
    
    if not our_messages and not altova_messages:
        print("❌ No messages loaded from either tool")
        return 1
    
    # Perform comparison
    diff = ValidationDiff(our_messages, altova_messages)
    analysis = diff.analyze()
    
    # Print results
    print_analysis(analysis)
    
    # Show unique messages if requested
    if args.show_unique:
        print(f"\n🔍 UNIQUE TO OUR TOOL (showing first {args.max_unique}):")
        our_unique = diff.get_unique_messages(ours_only=True)
        for i, msg in enumerate(our_unique[:args.max_unique], 1):
            print(f"  {i}. {msg}")
        
        print(f"\n🔍 UNIQUE TO ALTOVA (showing first {args.max_unique}):")
        altova_unique = diff.get_unique_messages(ours_only=False)
        for i, msg in enumerate(altova_unique[:args.max_unique], 1):
            print(f"  {i}. {msg}")
    
    # Write detailed analysis if requested
    if args.output_json:
        detailed = {
            "analysis": analysis,
            "our_unique_messages": [str(msg) for msg in diff.get_unique_messages(ours_only=True)],
            "altova_unique_messages": [str(msg) for msg in diff.get_unique_messages(ours_only=False)],
        }
        
        with open(args.output_json, 'w', encoding='utf-8') as f:
            json.dump(detailed, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Detailed analysis written to {args.output_json}")
    
    # Return exit code based on similarity
    if analysis['similarity_score'] >= 0.9:
        return 0  # Excellent
    elif analysis['similarity_score'] >= 0.7:
        return 1  # Good but with differences
    else:
        return 2  # Significant differences
    

if __name__ == "__main__":
    sys.exit(main())
