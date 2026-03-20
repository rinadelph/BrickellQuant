#!/usr/bin/env python3
"""
Extract Swarm system prompts and convert them to markdown format.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List
import re


def sanitize_filename(name: str) -> str:
    """Sanitize filename to be filesystem-friendly."""
    # Replace spaces and special characters with underscores
    name = re.sub(r'[^\w\-_\. ]', '_', name)
    name = name.replace(' ', '_')
    # Remove multiple underscores
    name = re.sub(r'_+', '_', name)
    return name.strip('_')


def extract_system_prompts(json_path: Path) -> Dict[str, Any]:
    """Extract system prompts from a JSON file."""
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"Error reading {json_path}: {e}")
        return {}


def format_agent_to_markdown(agent_name: str, agent_data: Dict[str, Any]) -> str:
    """Convert agent data to markdown format."""
    md_content = f"# {agent_name}\n\n"
    
    if isinstance(agent_data, dict):
        # Add description if available
        if 'description' in agent_data:
            md_content += f"## Description\n\n{agent_data['description']}\n\n"
        
        # Add system prompt if available
        if 'system_prompt' in agent_data:
            md_content += f"## System Prompt\n\n```\n{agent_data['system_prompt']}\n```\n\n"
        elif 'prompt' in agent_data:
            md_content += f"## System Prompt\n\n```\n{agent_data['prompt']}\n```\n\n"
        
        # Add other metadata
        metadata_keys = ['model', 'temperature', 'max_tokens', 'tools', 'capabilities']
        metadata_found = False
        
        for key in metadata_keys:
            if key in agent_data:
                if not metadata_found:
                    md_content += "## Configuration\n\n"
                    metadata_found = True
                
                value = agent_data[key]
                if isinstance(value, list):
                    md_content += f"- **{key.title()}**: {', '.join(str(v) for v in value)}\n"
                else:
                    md_content += f"- **{key.title()}**: {value}\n"
        
        if metadata_found:
            md_content += "\n"
        
        # Add any other keys as additional sections
        handled_keys = ['description', 'system_prompt', 'prompt'] + metadata_keys
        for key, value in agent_data.items():
            if key not in handled_keys and value:
                md_content += f"## {key.replace('_', ' ').title()}\n\n"
                if isinstance(value, (list, dict)):
                    md_content += f"```json\n{json.dumps(value, indent=2)}\n```\n\n"
                else:
                    md_content += f"{value}\n\n"
    
    elif isinstance(agent_data, str):
        # If the agent data is just a string (prompt), format it as such
        md_content += f"## System Prompt\n\n```\n{agent_data}\n```\n\n"
    
    return md_content


def process_json_file(json_path: Path, output_dir: Path, prefix: str = "") -> List[str]:
    """Process a JSON file and extract all agents/prompts to markdown files."""
    data = extract_system_prompts(json_path)
    created_files = []
    
    if not data:
        return created_files
    
    # Handle different JSON structures
    if isinstance(data, dict):
        # Check if it's a flat dictionary of prompts or nested structure
        for key, value in data.items():
            if isinstance(value, (dict, str)):
                # Create markdown file for this agent/prompt
                safe_filename = sanitize_filename(key)
                if prefix:
                    filename = f"{prefix}_{safe_filename}.md"
                else:
                    filename = f"{safe_filename}.md"
                
                output_path = output_dir / filename
                
                # Generate markdown content
                md_content = format_agent_to_markdown(key, value)
                
                # Write to file
                with open(output_path, 'w') as f:
                    f.write(md_content)
                
                created_files.append(str(output_path))
                print(f"Created: {output_path}")
    
    return created_files


def extract_plugin_agents(plugin_dir: Path, output_dir: Path) -> List[str]:
    """Extract agent markdown files from plugins directory."""
    created_files = []
    
    agents_dir = plugin_dir / "agents"
    if agents_dir.exists():
        for md_file in agents_dir.glob("*.md"):
            # Copy the markdown file to output directory
            output_path = output_dir / f"plugin_{md_file.name}"
            
            with open(md_file, 'r') as src:
                content = src.read()
            
            with open(output_path, 'w') as dst:
                dst.write(content)
            
            created_files.append(str(output_path))
            print(f"Copied: {output_path}")
    
    return created_files


def main():
    """Main function to extract all swarm prompts."""
    # Setup paths
    swarmos_dir = Path.home() / ".swarmos"
    output_dir = Path.cwd() / "swarm_system_prompts"
    
    # Create output directory
    output_dir.mkdir(exist_ok=True)
    print(f"Output directory: {output_dir}\n")
    
    all_files = []
    
    # Process main prompt files
    prompt_files = [
        ("system_prompts.json", "system"),
        ("agents.json", "agent"),
        ("custom_agents.json", "custom"),
        ("agent_profiles.json", "profile")
    ]
    
    for filename, prefix in prompt_files:
        json_path = swarmos_dir / filename
        if json_path.exists():
            print(f"\nProcessing {filename}...")
            files = process_json_file(json_path, output_dir, prefix)
            all_files.extend(files)
    
    # Process app directory files
    app_dir = swarmos_dir / "app"
    if app_dir.exists():
        for filename, prefix in prompt_files:
            json_path = app_dir / filename
            if json_path.exists():
                print(f"\nProcessing app/{filename}...")
                files = process_json_file(json_path, output_dir, f"app_{prefix}")
                all_files.extend(files)
    
    # Process plugin agents
    plugins_dir = swarmos_dir / "plugins"
    if plugins_dir.exists():
        for plugin_dir in plugins_dir.iterdir():
            if plugin_dir.is_dir():
                print(f"\nProcessing plugin: {plugin_dir.name}")
                files = extract_plugin_agents(plugin_dir, output_dir)
                all_files.extend(files)
    
    # Create index file
    index_path = output_dir / "README.md"
    with open(index_path, 'w') as f:
        f.write("# Swarm System Prompts\n\n")
        f.write("This directory contains all extracted system prompts from the Swarm OS.\n\n")
        f.write("## Files\n\n")
        
        # Group files by prefix
        grouped_files = {}
        for file_path in sorted(all_files):
            filename = Path(file_path).name
            prefix = filename.split('_')[0]
            if prefix not in grouped_files:
                grouped_files[prefix] = []
            grouped_files[prefix].append(filename)
        
        for prefix, files in grouped_files.items():
            f.write(f"\n### {prefix.title()}\n\n")
            for filename in sorted(files):
                f.write(f"- [{filename}]({filename})\n")
    
    print(f"\n\nExtraction complete! Created {len(all_files)} files in {output_dir}")
    print(f"Index file: {index_path}")


if __name__ == "__main__":
    main()