import cv2
import numpy as np

def extract_logo(input_path, output_path, target_color=(255, 255, 255)):
    # Read the image
    img = cv2.imread(input_path)
    if img is None:
        print(f"Error loading image {input_path}")
        return
        
    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Analyze image background brightness
    # The wall is mostly light, text is dark
    bg_color = np.percentile(gray, 90)
    
    # Invert and normalize: wall becomes 0, dark text becomes > 0
    alpha = np.clip((bg_color - gray.astype(float)) * 255.0 / bg_color, 0, 255)
    
    # Add some contrast to alpha channel (make text fully opaque, wall fully transparent)
    alpha = np.clip((alpha - 80) * 2.5, 0, 255).astype(np.uint8)
    
    # Apply a slight blur to smooth the edges
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)
    
    # Create final RGBA image
    rgba = np.zeros((img.shape[0], img.shape[1], 4), dtype=np.uint8)
    
    # Set the target color (BGR format)
    rgba[:, :, 0] = target_color[0] # B
    rgba[:, :, 1] = target_color[1] # G
    rgba[:, :, 2] = target_color[2] # R
    
    # Set the computed alpha
    rgba[:, :, 3] = alpha
    
    # Find bounding box of the non-transparent pixels to crop the image
    coords = cv2.findNonZero(alpha)
    if coords is not None:
        x, y, w, h = cv2.boundingRect(coords)
        pad = 20
        x = max(0, x - pad)
        y = max(0, y - pad)
        w = min(rgba.shape[1] - x, w + 2*pad)
        h = min(rgba.shape[0] - y, h + 2*pad)
        
        rgba = rgba[y:y+h, x:x+w]
        
    cv2.imwrite(output_path, rgba)
    print(f"Saved processed logo to {output_path}")

if __name__ == "__main__":
    # Pure white
    extract_logo("static/logo.png", "static/logo_extracted_white.png", target_color=(255, 255, 255))
