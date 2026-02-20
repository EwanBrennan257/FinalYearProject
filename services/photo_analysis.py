import os
from PIL import Image
from typing import Dict, List
from collections import Counter

#https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.quantize
#https://realpython.com/image-processing-with-the-python-pillow-library/
#https://stackoverflow.com/questions/3241929/how-to-find-the-dominant-most-common-color-in-an-image
class PhotoAnalyzer:
    def __init__(self):
        pass
    
    def analyze_photo(self, image_path: str) -> Dict:
        #analyzes photo colors
        try:
            print(f"🔍 Starting color analysis for: {image_path}")
            #results dictionary with fields
            results = {
                'success': True,
                'colors': [],
                'caption': '',
            }
            
            #analyze colors
            print("🎨 Analyzing colors...")
            colors = self._analyze_colors(image_path)
            print(f"✅ Found {len(colors)} dominant colors")
            results['colors'] = colors
            
            #generate summary
            results['summary'] = self._generate_summary(colors)
            
            print("✅ Analysis complete!")
            return results
            
        except Exception as e:
            print(f"❌ Analysis failed: {e}")
            return {
                'success': False,
                'error': f'Analysis failed: {str(e)}'
            }
    
    def _analyze_colors(self, image_path: str, num_colors: int = 6) -> List[Dict]:
        #extract dominant colors from image using pil
        #opens the image resize it for faster processing, reduces the image to a small pallet of colors
        #count how often each color appears, convert into percentages
        try:
            #open and resize image
            img = Image.open(image_path)
            img = img.convert('RGB')
            img = img.resize((150, 150))
            
            #ensures image is in standard rgb mode
            img_quantized = img.quantize(colors=num_colors, method=2)
            
            #convert back to RGB
            img_quantized = img_quantized.convert('RGB')
            
            #get all pixels
            pixels = list(img_quantized.getdata())
            
            #count occurrences of each color
            color_counts = Counter(pixels)
            most_common = color_counts.most_common(num_colors)
            
            #calculate percentages
            total_pixels = len(pixels)
            colors = []
            #percentafe of the image that this color covers
            for color, count in most_common:
                percentage = (count / total_pixels) * 100
                #convert rgb into tuple hex string
                hex_color = '#{:02x}{:02x}{:02x}'.format(*color)
                #store a structured recored for this dominant color
                colors.append({
                    'hex': hex_color,
                    'percentage': round(percentage, 1),
                    'rgb': {'r': color[0], 'g': color[1], 'b': color[2]}
                })
            #return with percentages
            return colors
          #if any error occurs return empty list so app won't crash  
        except Exception as e:
            print(f"❌ Color analysis error: {e}")
            return []
    #checks if colors is empty if no colors are detected return message
    def _generate_summary(self, colors: List[Dict]) -> str:
        if not colors or len(colors) == 0:
            return 'Photo color analysis complete.'
        #takes the first color as dominant one 
        dominant_color = colors[0]
        #converts the dominant color hex code into name
        color_name = self._get_color_name(dominant_color['hex'])
        #checks how much of the image dominant color covers
        percentage = dominant_color['percentage']
        
        return f'This photo features {color_name} tones ({percentage}% dominant color).'
    
    def _get_color_name(self, hex_color: str) -> str:
        try: #converts the hext string into integers
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            
            #determine color name based on RGB values
            if r > 200 and g > 200 and b > 200:
                return "light"
            elif r < 50 and g < 50 and b < 50:
                return "dark"
            elif r > 200 and g < 100 and b < 100:
                return "red"
            elif r < 100 and g > 200 and b < 100:
                return "green"
            elif r < 100 and g < 100 and b > 200:
                return "blue"
            elif r > 200 and g > 200 and b < 100:
                return "yellow"
            elif r > 200 and g > 100 and b < 100:
                return "orange"
            elif r > 100 and g < 100 and b > 200:
                return "purple"
            elif r < 150 and g > 150 and b > 200:
                return "cyan"
            elif r > 150 and g < 150 and b > 150:
                return "magenta"
            else:
                return "neutral"
        except:
            return "neutral"