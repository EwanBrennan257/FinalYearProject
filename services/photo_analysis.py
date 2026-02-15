import requests
import os
from PIL import Image
from typing import Dict, List
from collections import Counter

class PhotoAnalyzer:
    def __init__(self):
        """Initialize Hugging Face API client"""
        self.api_token = os.getenv('HUGGINGFACE_API_TOKEN')
        self.headers = {"Authorization": f"Bearer {self.api_token}"} if self.api_token else {}
    
    def analyze_photo(self, image_path: str) -> Dict:
        """
        Comprehensive photo breakdown using Hugging Face models
        """
        try:
            results = {
                'success': True,
                'labels': [],
                'colors': [],
                'caption': '',
                'objects': []
            }
            
            # 1. Generate image caption (describes the scene)
            caption = self._generate_caption(image_path)
            if caption:
                results['caption'] = caption
                # Extract labels from caption
                results['labels'] = self._extract_labels_from_caption(caption)
            
            # 2. Analyze colors (using PIL - completely free, no API)
            colors = self._analyze_colors(image_path)
            results['colors'] = colors
            
            # 3. Generate summary
            results['summary'] = self._generate_summary(results)
            
            return results
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Analysis failed: {str(e)}'
            }
    
    def _generate_caption(self, image_path: str) -> str:
        """Generate image caption using BLIP model"""
        API_URL = "https://api-inference.huggingface.co/models/Salesforce/blip-image-captioning-large"
        
        try:
            with open(image_path, "rb") as f:
                data = f.read()
            
            response = requests.post(API_URL, headers=self.headers, data=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, list) and len(result) > 0:
                    return result[0].get('generated_text', '')
            return ''
        except:
            return ''
    
    def _extract_labels_from_caption(self, caption: str) -> List[Dict]:
        """Extract meaningful labels from the caption"""
        # Common photography subjects
        photo_keywords = [
            'mountain', 'sky', 'sunset', 'sunrise', 'ocean', 'sea', 'beach', 
            'landscape', 'portrait', 'person', 'people', 'building', 'city',
            'tree', 'forest', 'night', 'day', 'cloud', 'water', 'rock',
            'bridge', 'street', 'road', 'car', 'nature', 'animal', 'bird'
        ]
        
        caption_lower = caption.lower()
        labels = []
        
        for keyword in photo_keywords:
            if keyword in caption_lower:
                labels.append({
                    'name': keyword.capitalize(),
                    'confidence': 85.0  # Approximate confidence
                })
        
        return labels[:10]  # Return top 10
    
    def _analyze_colors(self, image_path: str, num_colors: int = 6) -> List[Dict]:
        """Extract dominant colors using PIL (no API needed)"""
        try:
            img = Image.open(image_path)
            img = img.resize((150, 150))  # Resize for speed
            img = img.convert('RGB')
            
            pixels = list(img.getdata())
            
            # Count most common colors
            most_common = Counter(pixels).most_common(num_colors)
            
            colors = []
            total_pixels = len(pixels)
            
            for color, count in most_common:
                percentage = (count / total_pixels) * 100
                hex_color = '#{:02x}{:02x}{:02x}'.format(*color)
                colors.append({
                    'hex': hex_color,
                    'percentage': round(percentage, 1),
                    'rgb': {'r': color[0], 'g': color[1], 'b': color[2]}
                })
            
            return colors
        except:
            return []
    
    def _generate_summary(self, results: Dict) -> str:
        """Generate human-readable summary"""
        summary_parts = []
        
        if results.get('caption'):
            summary_parts.append(f"This photo shows {results['caption']}")
        
        if results.get('colors'):
            color_name = self._get_color_name(results['colors'][0]['hex'])
            summary_parts.append(f"with dominant {color_name} tones")
        
        return '. '.join(summary_parts) + '.' if summary_parts else 'Photo analyzed.'
    
    def _get_color_name(self, hex_color: str) -> str:
        """Convert hex to approximate color name"""
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        
        if r > 200 and g > 200 and b > 200:
            return "light"
        elif r < 50 and g < 50 and b < 50:
            return "dark"
        elif r > g and r > b:
            return "red"
        elif g > r and g > b:
            return "green"
        elif b > r and b > g:
            return "blue"
        else:
            return "neutral"