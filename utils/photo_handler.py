"""
Client-side photo compression for mobile cellular network compatibility.

This module provides a custom Streamlit component that compresses images
in the browser BEFORE uploading to reduce payload size and prevent timeouts
on cellular networks.
"""

import streamlit as st
import streamlit.components.v1 as components
from typing import List, Dict, Any
import base64
from io import BytesIO
from PIL import Image
from utils.logger import setup_logger

logger = setup_logger(__name__)


def create_photo_uploader_with_compression(
    max_photos: int = 20,
    max_size_mb: float = 8,
    target_max_dimension: int = 1600,
    jpeg_quality: int = 75
) -> List[Dict[str, Any]]:
    """
    Photo uploader with client-side compression.
    
    Compresses images in the browser using JavaScript Canvas API before
    uploading to Streamlit server. This reduces upload payload from 5-10MB
    per photo to <500KB, making uploads work reliably on cellular networks.
    
    Args:
        max_photos: Maximum number of photos allowed
        max_size_mb: Maximum size per photo (before compression)
        target_max_dimension: Target max dimension for resized images
        jpeg_quality: JPEG compression quality (0-100)
    
    Returns:
        List of dicts: [{"name": str, "data": bytes, "size": int}, ...]
    """
    
    # JavaScript for client-side compression
    compression_js = f"""
    <div id="photo-upload-container" style="padding: 20px; border: 2px dashed #ccc; border-radius: 10px; text-align: center; background: #f9f9f9;">
        <input type="file" id="photoInput" multiple accept="image/*" 
               style="display:none;">
        <button id="uploadBtn" onclick="document.getElementById('photoInput').click()"
                style="padding: 15px 30px; background: #FF4B4B; color: white; 
                       border: none; border-radius: 8px; cursor: pointer; 
                       font-size: 18px; font-weight: bold; box-shadow: 0 2px 4px rgba(0,0,0,0.2);
                       transition: background 0.3s;">
            📷 Select Photos (up to {max_photos})
        </button>
        <div id="status" style="margin-top: 15px; font-size: 16px; color: #333; font-weight: 500;"></div>
        <div id="progress" style="margin-top: 15px; font-size: 14px; color: #666; line-height: 1.8; text-align: left; max-width: 600px; margin-left: auto; margin-right: auto;"></div>
    </div>

    <script>
    const MAX_DIMENSION = {target_max_dimension};
    const JPEG_QUALITY = {jpeg_quality / 100};
    const MAX_SIZE_MB = {max_size_mb};
    
    let processedPhotos = [];
    
    // Add hover effect
    document.getElementById('uploadBtn').addEventListener('mouseenter', function() {{
        this.style.background = '#E63946';
    }});
    document.getElementById('uploadBtn').addEventListener('mouseleave', function() {{
        this.style.background = '#FF4B4B';
    }});
    
    document.getElementById('photoInput').addEventListener('change', async (e) => {{
        const files = Array.from(e.target.files).slice(0, {max_photos});
        const statusDiv = document.getElementById('status');
        const progressDiv = document.getElementById('progress');
        
        if (files.length === 0) return;
        
        statusDiv.innerHTML = `<strong>🔄 Processing ${{files.length}} photo(s)...</strong>`;
        statusDiv.style.color = '#FF4B4B';
        processedPhotos = [];
        progressDiv.innerHTML = '';
        
        for (let i = 0; i < files.length; i++) {{
            const file = files[i];
            const originalSizeMB = (file.size / 1024 / 1024).toFixed(2);
            
            progressDiv.innerHTML += `<div style="padding: 5px; border-bottom: 1px solid #eee;">📸 ${{i+1}}/${{files.length}}: ${{file.name}} (${{originalSizeMB}} MB) - compressing...</div>`;
            
            try {{
                const compressed = await compressImage(file);
                processedPhotos.push(compressed);
                
                const finalSizeMB = (compressed.size / 1024 / 1024).toFixed(2);
                const finalSizeKB = (compressed.size / 1024).toFixed(0);
                const reduction = (((file.size - compressed.size) / file.size) * 100).toFixed(0);
                
                // Update last line to show success
                const lines = progressDiv.querySelectorAll('div');
                if (lines.length > 0) {{
                    lines[lines.length - 1].innerHTML = `<span style="color: green;">✓ ${{file.name}}: ${{originalSizeMB}} MB → ${{finalSizeKB}} KB (saved ${{reduction}}%)</span>`;
                }}
            }} catch (err) {{
                progressDiv.innerHTML += `<div style="color: red; padding: 5px;">✗ ${{file.name}} failed: ${{err.message}}</div>`;
                console.error('Compression error:', err);
            }}
        }}
        
        statusDiv.innerHTML = `<strong style="color: green;">✓ Ready! ${{processedPhotos.length}} photo(s) compressed and ready to upload</strong>`;
        
        // Send to Streamlit
        window.parent.postMessage({{
            type: 'streamlit:setComponentValue',
            data: processedPhotos
        }}, '*');
    }});
    
    async function compressImage(file) {{
        return new Promise((resolve, reject) => {{
            const reader = new FileReader();
            
            reader.onload = (e) => {{
                const img = new Image();
                
                img.onload = () => {{
                    // Calculate new dimensions
                    let width = img.width;
                    let height = img.height;
                    
                    if (width > MAX_DIMENSION || height > MAX_DIMENSION) {{
                        if (width > height) {{
                            height = Math.round((height / width) * MAX_DIMENSION);
                            width = MAX_DIMENSION;
                        }} else {{
                            width = Math.round((width / height) * MAX_DIMENSION);
                            height = MAX_DIMENSION;
                        }}
                    }}
                    
                    // Create canvas
                    const canvas = document.createElement('canvas');
                    canvas.width = width;
                    canvas.height = height;
                    const ctx = canvas.getContext('2d');
                    
                    // Draw image with white background (handles transparency)
                    ctx.fillStyle = '#FFFFFF';
                    ctx.fillRect(0, 0, width, height);
                    ctx.drawImage(img, 0, 0, width, height);
                    
                    // Convert to JPEG blob
                    canvas.toBlob((blob) => {{
                        if (!blob) {{
                            reject(new Error('Failed to create blob'));
                            return;
                        }}
                        
                        const reader2 = new FileReader();
                        reader2.onload = () => {{
                            const base64 = reader2.result.split(',')[1];
                            resolve({{
                                name: file.name.replace(/\.[^/.]+$/, '.jpg'),  // Force .jpg extension
                                data: base64,
                                size: blob.size
                            }});
                        }};
                        reader2.onerror = reject;
                        reader2.readAsDataURL(blob);
                    }}, 'image/jpeg', JPEG_QUALITY);
                }};
                
                img.onerror = () => reject(new Error('Failed to load image'));
                img.src = e.target.result;
            }};
            
            reader.onerror = () => reject(new Error('Failed to read file'));
            reader.readAsDataURL(file);
        }});
    }}
    </script>
    """
    
    # Render component with dynamic height
    result = components.html(compression_js, height=300, scrolling=False)
    
    # Process returned data
    if result and isinstance(result, list):
        photos = []
        for photo in result:
            try:
                if not isinstance(photo, dict):
                    continue
                    
                # Decode base64
                img_bytes = base64.b64decode(photo['data'])
                
                # Quick validation
                try:
                    Image.open(BytesIO(img_bytes)).verify()
                except Exception as e:
                    logger.error("Photo validation failed", extra={
                        "photo_name": photo.get('name', 'unknown'),
                        "error": str(e)
                    })
                    continue
                
                photos.append({
                    "name": photo['name'],
                    "data": img_bytes,
                    "size": photo.get('size', len(img_bytes))
                })
                
                logger.info("Photo compressed client-side", extra={
                    "photo_name": photo['name'],
                    "size_kb": len(img_bytes) / 1024
                })
                
            except Exception as e:
                logger.error("Failed to process compressed photo", extra={
                    "photo_name": photo.get('name', 'unknown'),
                    "error": str(e)
                })
        
        return photos
    
    return []
