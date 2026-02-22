"""Pipeline configuration utilities"""

import yaml
from pathlib import Path
from typing import Optional, Dict

from src.utils.logger import logger

# Cache for loaded config
_config_cache: Optional[Dict] = None


def load_pipeline_config(config_path: Optional[Path] = None) -> Dict:
    """
    Load pipeline configuration from YAML file.
    
    Args:
        config_path: Path to config file. If None, uses default location.
        
    Returns:
        Dictionary containing configuration
    """
    global _config_cache
    
    if config_path is None:
        # Default to scripts/pipeline_config.yaml relative to project root
        config_path = Path(__file__).parent.parent.parent / "scripts" / "pipeline_config.yaml"
    
    # Use cached config if available
    if _config_cache is not None:
        return _config_cache
    
    try:
        if not config_path.exists():
            logger.warning(f"Config file not found at {config_path}, using empty config")
            _config_cache = {}
            return _config_cache
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f) or {}
        
        _config_cache = config
        logger.debug(f"Loaded pipeline config from {config_path}")
        return config
        
    except Exception as e:
        logger.error(f"Error loading pipeline config: {e}", exc_info=True)
        _config_cache = {}
        return _config_cache


def get_headless_mode(config: Optional[Dict] = None) -> bool:
    """
    Get headless mode from config, defaulting to False.
    
    Args:
        config: Configuration dictionary. If None, loads from default location.
        
    Returns:
        True if headless mode should be enabled, False otherwise
    """
    if config is None:
        config = load_pipeline_config()
    
    # Navigate to browser.headless path
    browser_config = config.get("browser", {})
    headless = browser_config.get("headless", False)
    
    return bool(headless)


def clear_config_cache():
    """Clear the cached config (useful for testing or reloading config)"""
    global _config_cache
    _config_cache = None
