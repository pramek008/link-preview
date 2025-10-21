from bs4 import BeautifulSoup, NavigableString
from markdownify import markdownify as md
import re
import uuid
from urllib.parse import urlparse
from typing import Optional, Union, List
from enum import Enum
import logging
from utils.playwright_utils import playwright_manager

logger = logging.getLogger(__name__)

class OutputFormat(str, Enum):
    """Format output untuk markdown"""
    STRING = "string"  # Default: string dengan \n
    LINES = "lines"    # Array of lines
    PRETTY = "pretty"  # JSON structured dengan metadata

class HTMLToMarkdownService:
    """Service untuk scraping HTML dan convert ke Markdown"""
    
    @staticmethod
    def extract_code_text(code_elem):
        """
        Extract text from code block while preserving:
        - Line breaks
        - Indentation (leading spaces/tabs)  
        - Special characters (tree structure, underscore, etc)
        """
        classes = code_elem.get('class', [])
        has_whitespace_pre = any('whitespace-pre' in str(c) for c in classes)
        
        if has_whitespace_pre:
            text = code_elem.get_text()
            return text
        
        # Fallback: untuk code block lama yang pakai nested spans
        lines = []
        current_line = []
        
        def process_node(node):
            """Recursively process nodes"""
            if isinstance(node, NavigableString):
                text = str(node)
                if text:
                    current_line.append(text)
            elif node.name == 'br':
                if current_line:
                    lines.append(''.join(current_line))
                    current_line.clear()
                lines.append('')
            elif node.name in ['span', 'code']:
                for child in node.children:
                    process_node(child)
        
        process_node(code_elem)
        
        if current_line:
            lines.append(''.join(current_line))
        
        result = '\n'.join(lines)
        return result.strip('\n')
    
    @staticmethod
    def clean_html(html_str: str, skip_short_code_blocks: bool = True) -> str:
        """
        Clean GPT-style HTML and remove 'Salin kode' sections, wrappers, SVG icons, etc.
        """
        soup = BeautifulSoup(html_str, "html.parser")

        # Hapus tombol 'Salin' dan semua button
        for button in soup.find_all("button"):
            button.decompose()
        
        # Hapus semua SVG
        for svg in soup.find_all("svg"):
            svg.decompose()

        # Hapus wrapper div yang tidak penting
        for selector in [
            ".bg-token-bg-elevated-secondary",
            ".flex.gap-1.items-center",
        ]:
            for elem in soup.select(selector):
                elem.decompose()

        # Normalisasi blok <pre><code> jadi Markdown-style ```lang```
        for pre in soup.find_all("pre"):
            code = pre.find("code")
            if code:
                lang = ""
                
                # Cek dari class code element (e.g., language-dart)
                code_classes = code.get('class', [])
                for cls in code_classes:
                    cls_str = str(cls)
                    if 'language-' in cls_str:
                        lang = cls_str.replace('language-', '')
                        break
                
                # Cek dari div (fallback)
                if not lang:
                    for div in pre.find_all("div", class_=True):
                        text = div.get_text().strip().lower()
                        if text and len(text) < 20 and text in [
                            "python", "javascript", "html", "css", "nginx", 
                            "yaml", "scss", "csharp", "bash", "json", "sql",
                            "typescript", "markdown", "xml", "go", "rust", 
                            "text", "dart", "kotlin", "swift", "java", "c", "cpp",
                            "diff", "shell", "undefined"
                        ]:
                            lang = text
                            div.decompose()
                            break
                
                # Extract text dengan preserve whitespace
                code_text = HTMLToMarkdownService.extract_code_text(code)
                
                # Filter: Skip jika terlalu pendek DAN bukan tree/code structure
                if skip_short_code_blocks:
                    is_tree = any(char in code_text for char in ['├', '│', '└', '─'])
                    is_version = re.match(r'^[\d\.\(\)\s]+$', code_text.strip())
                    
                    if not is_tree:
                        tokens = re.findall(r'\w+', code_text)
                        if len(tokens) < 4 and len(code_text) < 50:
                            if is_version:
                                pre.replace_with(soup.new_string(f"\n{code_text.strip()}\n"))
                                continue
                
                # Buat code block markdown
                markdown_code = f"\n```{lang}\n{code_text}\n```\n"
                
                # Replace dengan tag khusus
                placeholder = soup.new_tag("codeblock-placeholder")
                placeholder.string = markdown_code
                pre.replace_with(placeholder)
            else:
                # Kalau ga ada <code>, ambil text langsung
                text = pre.get_text()
                if skip_short_code_blocks and len(text.split()) < 3:
                    pre.replace_with(soup.new_string(f"\n{text.strip()}\n"))
                else:
                    markdown_code = f"\n```\n{text}\n```\n"
                    placeholder = soup.new_tag("codeblock-placeholder")
                    placeholder.string = markdown_code
                    pre.replace_with(placeholder)

        return str(soup)
    
    @staticmethod
    def post_process_markdown(markdown: str) -> str:
        """
        Post-process markdown untuk fix formatting issues
        """
        lines = markdown.split('\n')
        result = []
        in_code_block = False
        empty_count = 0
        prev_was_list = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Deteksi code block fence
            if stripped.startswith('```'):
                in_code_block = not in_code_block
                result.append(line)
                empty_count = 0
                prev_was_list = False
                continue
            
            # Di dalam code block: preserve semua
            if in_code_block:
                result.append(line)
                continue
            
            # Deteksi list items
            is_list = bool(re.match(r'^[\s]*[\*\-\+]\s+', line) or 
                          re.match(r'^[\s]*\d+\.\s+', line) or
                          re.match(r'^[\s]*\[\s*[xX]?\s*\]\s+', line) or
                          re.match(r'^[\s]*\(\s*[xX]?\s*\)\s+', line))
            
            # Empty line handling
            if not stripped:
                empty_count += 1
                # Allow max 1 empty line, tapi preserve spacing antara list dan non-list
                if empty_count <= 1:
                    result.append(line)
                elif prev_was_list and i + 1 < len(lines) and lines[i + 1].strip() and not re.match(r'^[\s]*[\*\-\+\d]', lines[i + 1]):
                    # Preserve blank line after list sebelum content lain
                    result.append(line)
                continue
            
            # Non-empty line
            empty_count = 0
            
            # Fix indentasi list yang hilang
            if is_list:
                # Cek apakah ini nested list (harusnya ada indent)
                next_line_idx = i + 1
                if next_line_idx < len(lines):
                    next_line = lines[next_line_idx].strip()
                    # Jika next line juga list dan ini continuation, preserve struktur
                    if re.match(r'^[\*\-\+\d]', next_line):
                        result.append(line)
                        prev_was_list = True
                        continue
                
                result.append(line)
                prev_was_list = True
            else:
                result.append(line)
                prev_was_list = False
        
        # Join dan cleanup multiple newlines
        output = '\n'.join(result)
        
        # Fix: Multiple consecutive blank lines -> max 2
        output = re.sub(r'\n{4,}', '\n\n\n', output)
        
        # Fix: Space sebelum list items yang kehilangan indentasinya
        # Restore nested list indentation
        lines = output.split('\n')
        fixed_lines = []
        in_list = False
        
        for line in lines:
            stripped = line.strip()
            
            # Check if it's a list item
            if re.match(r'^[\*\-\+]\s+', stripped) or re.match(r'^\d+\.\s+', stripped):
                # Jika sebelumnya bukan list, ini top-level
                if not in_list:
                    fixed_lines.append(line)
                    in_list = True
                else:
                    # Nested list: tambahkan indent
                    # Cek apakah sudah ada indent
                    if line.startswith('  ') or line.startswith('\t'):
                        fixed_lines.append(line)
                    else:
                        # Indent nested lists
                        fixed_lines.append('  ' + line)
            elif stripped.startswith('[') or stripped.startswith('('):
                # Checkbox/radio items
                fixed_lines.append(line)
                in_list = True
            elif stripped == '':
                fixed_lines.append(line)
                # Keep in_list state through blank lines
            else:
                fixed_lines.append(line)
                in_list = False
        
        return '\n'.join(fixed_lines).strip()
    
    @staticmethod
    def format_output(markdown: str, format_type: OutputFormat = OutputFormat.STRING) -> Union[str, List[str], dict]:
        """
        Format output sesuai kebutuhan
        
        Args:
            markdown: Markdown string
            format_type: Format output yang diinginkan
            
        Returns:
            String, list of lines, atau structured dict
        """
        if format_type == OutputFormat.STRING:
            return markdown
        
        elif format_type == OutputFormat.LINES:
            # Return sebagai array of lines (lebih mudah di-handle)
            return markdown.split('\n')
        
        elif format_type == OutputFormat.PRETTY:
            # Return structured dengan metadata
            lines = markdown.split('\n')
            
            # Detect elements
            headings = []
            code_blocks = []
            lists = []
            
            in_code = False
            code_start = 0
            
            for i, line in enumerate(lines):
                # Headings
                if line.strip().startswith('#'):
                    level = len(line) - len(line.lstrip('#'))
                    text = line.lstrip('#').strip()
                    headings.append({
                        'line': i,
                        'level': level,
                        'text': text
                    })
                
                # Code blocks
                if line.strip().startswith('```'):
                    if not in_code:
                        in_code = True
                        code_start = i
                        lang = line.strip()[3:].strip()
                    else:
                        in_code = False
                        code_blocks.append({
                            'start': code_start,
                            'end': i,
                            'language': lang if 'lang' in locals() else '',
                            'lines': lines[code_start+1:i]
                        })
                
                # Lists
                if re.match(r'^[\s]*[\*\-\+\d\[\(]', line.strip()):
                    lists.append({
                        'line': i,
                        'text': line.strip()
                    })
            
            return {
                'content': lines,
                'metadata': {
                    'total_lines': len(lines),
                    'headings': headings,
                    'code_blocks': code_blocks,
                    'lists': lists
                }
            }
        
        return markdown
    
    @staticmethod
    def convert_html_to_markdown(
        html: str, 
        strip_tags=None, 
        convert_tags=None, 
        skip_short_code_blocks: bool = True,
        output_format: OutputFormat = OutputFormat.STRING
    ) -> Union[str, List[str], dict]:
        """
        Convert cleaned HTML string to Markdown.
        
        Args:
            html: HTML string to convert
            strip_tags: Tags to strip
            convert_tags: Tags to convert
            skip_short_code_blocks: Skip short code blocks
            output_format: Format untuk output (string, lines, atau pretty)
        """
        # Clean HTML dulu (convert <pre><code> jadi placeholder)
        cleaned_html = HTMLToMarkdownService.clean_html(
            html, 
            skip_short_code_blocks=skip_short_code_blocks
        )
        
        # Parse lagi untuk extract code block placeholders
        soup = BeautifulSoup(cleaned_html, "html.parser")
        
        # Extract semua code blocks ke dictionary dengan UUID marker
        code_blocks = {}
        for placeholder in soup.find_all("codeblock-placeholder"):
            marker = f"XCODEBLOCKMK{uuid.uuid4().hex[:8].upper()}X"
            code_blocks[marker] = placeholder.string
            placeholder.replace_with(soup.new_string(marker))
        
        # Convert ke markdown dengan preserve whitespace
        markdown = md(
            str(soup), 
            strip=strip_tags or [],
            heading_style="ATX",  # Use # style headers
            bullets="-",  # Use - for unordered lists
        )
        
        # Restore code blocks
        for marker, code_block in code_blocks.items():
            markdown = markdown.replace(marker, code_block)
        
        # Post-process untuk fix formatting
        markdown = HTMLToMarkdownService.post_process_markdown(markdown)
        
        # Format output sesuai kebutuhan
        return HTMLToMarkdownService.format_output(markdown, output_format)
    
    async def scrape_and_convert(
        self,
        url: str,
        skip_short_code_blocks: bool = True,
        timeout: int = 30000,
        wait_until: str = "networkidle",
        selector: Optional[str] = None,
        output_format: OutputFormat = OutputFormat.STRING
    ) -> dict:
        """
        Scrape HTML dari URL dan convert ke Markdown
        
        Args:
            url: URL yang akan di-scrape
            skip_short_code_blocks: Skip code blocks yang terlalu pendek
            timeout: Timeout untuk loading page (ms)
            wait_until: Wait until condition ('load', 'domcontentloaded', 'networkidle')
            selector: CSS selector untuk extract specific element (optional)
            output_format: Format output (string, lines, pretty)
        
        Returns:
            dict: {
                'success': bool,
                'url': str,
                'markdown': str | list | dict (tergantung output_format),
                'error': str (if any)
            }
        """
        domain = urlparse(url).netloc
        
        try:
            async with playwright_manager.get_page(domain=domain) as page:
                # Block unnecessary resources
                await page.route("**/*", lambda route, request: (
                    route.continue_() if request.resource_type in ['document', 'script', 'xhr', 'fetch'] 
                    else route.abort()
                ))
                
                # Navigate to URL
                logger.info(f"Navigating to {url}")
                response = await page.goto(url, wait_until=wait_until, timeout=timeout)
                
                if not response or response.status >= 400:
                    return {
                        'success': False,
                        'url': url,
                        'markdown': '' if output_format == OutputFormat.STRING else [],
                        'error': f'Failed to load page. Status: {response.status if response else "No response"}'
                    }
                
                # Extract HTML
                if selector:
                    # Extract specific element
                    element = await page.query_selector(selector)
                    if element:
                        html_content = await element.inner_html()
                    else:
                        return {
                            'success': False,
                            'url': url,
                            'markdown': '' if output_format == OutputFormat.STRING else [],
                            'error': f'Selector "{selector}" not found'
                        }
                else:
                    # Extract full page
                    html_content = await page.content()
                
                # Convert to markdown
                logger.info(f"Converting HTML to Markdown for {url}")
                markdown_output = self.convert_html_to_markdown(
                    html_content,
                    skip_short_code_blocks=skip_short_code_blocks,
                    output_format=output_format
                )
                
                return {
                    'success': True,
                    'url': str(response.url),  # Final URL after redirects
                    'markdown': markdown_output,
                    'title': await page.title(),
                    'format': output_format.value,
                    'error': None
                }
                
        except Exception as e:
            logger.error(f"Error scraping {url}: {str(e)}")
            return {
                'success': False,
                'url': url,
                'markdown': '' if output_format == OutputFormat.STRING else [],
                'error': str(e)
            }
    
    async def convert_from_html_string(
        self,
        html: str,
        skip_short_code_blocks: bool = True
    ) -> dict:
        """
        Convert HTML string ke Markdown (tanpa scraping)
        
        Args:
            html: HTML string
            skip_short_code_blocks: Skip code blocks yang terlalu pendek
        
        Returns:
            dict: {
                'success': bool,
                'markdown': str,
                'error': str (if any)
            }
        """
        try:
            markdown_output = self.convert_html_to_markdown(
                html,
                skip_short_code_blocks=skip_short_code_blocks
            )
            
            return {
                'success': True,
                'markdown': markdown_output,
                'error': None
            }
        except Exception as e:
            logger.error(f"Error converting HTML: {str(e)}")
            return {
                'success': False,
                'markdown': '',
                'error': str(e)
            }