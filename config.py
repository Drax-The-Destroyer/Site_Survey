"""
Centralized configuration for the Site Survey application.

All magic numbers, layout constants, colors, and paths are defined here
to avoid scattering hardcoded values throughout the codebase.
"""

from typing import Tuple


class Config:
    """Application configuration constants."""
    
    # ==================== Survey Settings ====================
    
    # Photo upload constraints
    MAX_PHOTOS_DEFAULT: int = 20
    MAX_PHOTO_SIZE_MB: float = 8.0
    PHOTO_QUALITY_JPEG: int = 75
    MAX_IMAGE_DIMENSION: int = 1600
    
    # Photo Upload Settings (Mobile)
    PHOTO_UPLOAD_TIMEOUT_SECONDS: int = 60  # Per photo
    ENABLE_CLIENT_COMPRESSION: bool = True  # Feature flag
    
    # Hero Image Display
    HERO_IMAGE_MAX_WIDTH_MOBILE: str = "100vw"  # Fill mobile screen
    HERO_IMAGE_MAX_HEIGHT_MOBILE: str = "60vh"  # Limit vertical space
    HERO_IMAGE_MAX_WIDTH_DESKTOP: str = "600px"
    
    # Form settings
    TIME_PICKER_STEP_MINUTES: int = 30
    AUTOSAVE_INTERVAL_SECONDS: int = 30
    
    # ==================== PDF Layout Constants ====================
    
    # Section and row heights
    PDF_SECTION_HEIGHT: float = 8.0
    PDF_ROW_HEIGHT: float = 6.5
    PDF_TABLE_HEIGHT: float = 7.0
    
    # Spacing
    PDF_SPACE_AFTER_SECTION: float = 1.2
    PDF_SPACE_AFTER_BLOCK: float = 1.2
    
    # Horizontal rule
    PDF_HR_THICKNESS: float = 0.4
    PDF_HR_PAD: float = 2.0
    
    # ==================== PDF Colors (RGB tuples) ====================
    
    PDF_GRAY: Tuple[int, int, int] = (230, 230, 230)
    PDF_DARK: Tuple[int, int, int] = (60, 60, 60)
    PDF_LIGHT: Tuple[int, int, int] = (120, 120, 120)
    PDF_LINE_GRAY: Tuple[int, int, int] = (200, 200, 200)
    
    # ==================== Paths ====================
    
    DATA_DIR: str = "data"
    MEDIA_DIR: str = "data/media"
    LOGS_DIR: str = "logs"
    DATABASE_PATH: str = "data/surveys.db"
    
    # ==================== Database & Autosave ====================
    
    AUTOSAVE_INTERVAL_SECONDS: int = 30
    MAX_DRAFT_AGE_DAYS: int = 30  # For future cleanup job
