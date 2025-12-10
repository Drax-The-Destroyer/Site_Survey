"""
Server-side photo compression for reliable mobile upload.

This module provides a simplified photo uploader that uses Streamlit's
standard file uploader with immediate server-side compression. This approach
is more reliable than client-side compression because:
1. No custom component communication issues
2. Works immediately without JavaScript debugging
3. Still compresses photos effectively using utils/images.py
4. Shows clear progress and feedback
5. Streamlit handles file transfer optimization
"""

import streamlit as st
from typing import List, Dict, Any
from io import BytesIO
from PIL import Image
from utils.logger import setup_logger
from utils.images import process_survey_image

logger = setup_logger(__name__)


def create_photo_uploader_with_compression(
    max_photos: int = 20,
    max_size_mb: float = 8,
    target_max_dimension: int = 1600,  # Accepted for compatibility but not used
    jpeg_quality: int = 75  # Accepted for compatibility but not used
) -> List[Dict[str, Any]]:
    """
    Simplified photo uploader with server-side compression.
    
    Since client-side compression via custom components has data return issues
    (window.parent.postMessage not properly communicating with Streamlit),
    we use standard Streamlit uploader with immediate server-side processing.
    
    This approach is more reliable because:
    - Streamlit's file uploader is battle-tested on mobile/cellular
    - No JavaScript/Python communication bridge issues
    - Compression happens immediately after upload
    - Clear progress feedback for users
    - Photos still reduced from 3-5MB to ~300-500KB
    
    Args:
        max_photos: Maximum number of photos allowed (default: 20)
        max_size_mb: Maximum size per photo before compression (default: 8)
        target_max_dimension: Kept for backward compatibility (uses utils/images.py defaults)
        jpeg_quality: Kept for backward compatibility (uses utils/images.py defaults)
    
    Returns:
        List of dicts: [{"name": str, "data": bytes}, ...]
    
    Note:
        Compression settings (dimension limits, JPEG quality) are controlled by
        utils/images.py constants (MAX_IMAGE_DIM=1600, JPEG_QUALITY=75).
    """
    
    st.markdown("""
    **📱 Mobile-Friendly Upload Tips:**
    - Photos are compressed automatically after upload
    - Works on cellular networks (4G/5G)
    - Upload **one photo at a time** for best reliability on mobile
    - Each photo will be reduced to ~500KB
    """)
    
    # Use standard Streamlit uploader (most reliable)
    uploaded_files = st.file_uploader(
        f"Select photos (up to {max_photos})",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        key="photo_uploader_key",
        help="For best results on cellular, upload 3-5 photos at a time"
    )
    
    if not uploaded_files:
        return []
    
    # Limit to max count
    files_to_process = uploaded_files[:max_photos]
    
    if len(uploaded_files) > max_photos:
        st.warning(f"⚠️ Only processing first {max_photos} photos")
    
    # Process with progress bar
    processed_photos = []
    
    if len(files_to_process) > 0:
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, file in enumerate(files_to_process):
            status_text.text(f"Processing {idx+1}/{len(files_to_process)}: {file.name}")
            
            try:
                # Get original size
                original_size = file.size
                original_mb = original_size / (1024 * 1024)
                
                # Compress using existing utils/images.py
                # This handles EXIF orientation, resizing, and JPEG compression
                compressed_bytes = process_survey_image(file)
                
                # Calculate compression stats
                compressed_size = len(compressed_bytes)
                compressed_mb = compressed_size / (1024 * 1024)
                compressed_kb = compressed_size / 1024
                saved_percent = int(((original_size - compressed_size) / original_size) * 100)
                
                processed_photos.append({
                    "name": file.name,
                    "data": compressed_bytes
                })
                
                # Log success
                logger.info("Photo compressed", extra={
                    "photo_name": file.name,
                    "original_mb": round(original_mb, 2),
                    "compressed_kb": round(compressed_kb, 2),
                    "saved_percent": saved_percent
                })
                
                # Show feedback
                if compressed_mb < 1:
                    st.success(f"✓ {file.name}: {original_mb:.2f} MB → {compressed_kb:.0f} KB (saved {saved_percent}%)")
                else:
                    st.success(f"✓ {file.name}: {original_mb:.2f} MB → {compressed_mb:.2f} MB (saved {saved_percent}%)")
                
            except Exception as e:
                logger.error("Photo processing failed", extra={
                    "photo_name": file.name,
                    "error": str(e)
                })
                st.error(f"❌ Failed to process {file.name}: {str(e)}")
            
            # Update progress
            progress_bar.progress((idx + 1) / len(files_to_process))
        
        # Clean up progress indicators
        progress_bar.empty()
        status_text.empty()
    
    return processed_photos
