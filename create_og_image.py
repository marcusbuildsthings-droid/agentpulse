#!/usr/bin/env python3
"""Create OG image for AgentPulse"""

from PIL import Image, ImageDraw, ImageFont
import os

def create_og_image():
    # Create image
    width, height = 1200, 630
    img = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(img)
    
    # Gradient background (simple two-color approximation)
    for y in range(height):
        # Interpolate between two colors
        ratio = y / height
        r = int(102 * (1-ratio) + 118 * ratio)  # 667eea to 764ba2
        g = int(126 * (1-ratio) + 75 * ratio)
        b = int(234 * (1-ratio) + 162 * ratio)
        
        draw.rectangle([(0, y), (width, y+1)], fill=(r, g, b))
    
    # Try to load system fonts
    try:
        # Try common macOS fonts
        title_font = ImageFont.truetype("/System/Library/Fonts/SF-Pro-Display-Bold.otf", 80)
        subtitle_font = ImageFont.truetype("/System/Library/Fonts/SF-Pro-Display-Light.otf", 36)
        badge_font = ImageFont.truetype("/System/Library/Fonts/SF-Pro-Display-Medium.otf", 20)
    except:
        try:
            title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 80)
            subtitle_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
            badge_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
        except:
            # Fallback to default
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()
            badge_font = ImageFont.load_default()
    
    # Add text
    white = (255, 255, 255)
    light_white = (255, 255, 255, 242)  # 95% opacity approximation
    
    # Title
    title = "AgentPulse"
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_width = title_bbox[2] - title_bbox[0]
    title_x = (width - title_width) // 2
    title_y = 200
    draw.text((title_x, title_y), title, font=title_font, fill=white)
    
    # Subtitle
    subtitle = "Monitor Your AI Agents"
    subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
    subtitle_x = (width - subtitle_width) // 2
    subtitle_y = title_y + 100
    draw.text((subtitle_x, subtitle_y), subtitle, font=subtitle_font, fill=white)
    
    # Badge
    badge_text = "Real-time insights for indie developers"
    badge_bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
    badge_width = badge_bbox[2] - badge_bbox[0]
    badge_height = badge_bbox[3] - badge_bbox[1]
    
    badge_padding = 24
    badge_x = (width - badge_width - badge_padding*2) // 2
    badge_y = subtitle_y + 80
    
    # Draw badge background
    badge_bg = (255, 255, 255, 38)  # 15% opacity approximation
    draw.rounded_rectangle(
        [(badge_x, badge_y), (badge_x + badge_width + badge_padding*2, badge_y + badge_height + badge_padding)],
        radius=30,
        fill=(255, 255, 255, 40)
    )
    
    # Badge text
    draw.text((badge_x + badge_padding, badge_y + badge_padding//2), badge_text, font=badge_font, fill=white)
    
    # Add subtle pattern (dots)
    for x in range(0, width, 50):
        for y in range(0, height, 50):
            if (x + y) % 100 == 0:  # Sparse pattern
                draw.ellipse([(x-2, y-2), (x+2, y+2)], fill=(255, 255, 255, 25))
    
    # Save image
    output_path = "/Users/ape/clawd/projects/agentops/og-image.png"
    img.save(output_path, "PNG")
    print(f"OG image saved to: {output_path}")
    return output_path

if __name__ == "__main__":
    create_og_image()