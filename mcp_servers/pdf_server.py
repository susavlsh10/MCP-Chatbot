import asyncio
from pathlib import Path
from typing import Dict, List, Optional
import PyPDF2
import fitz  # PyMuPDF for better text extraction
from fastmcp import FastMCP
import re
import logging

# In-memory storage for loaded PDFs
pdf_storage: Dict[str, Dict] = {}

# Initialize FastMCP server
mcp = FastMCP("PDF Processor")

@mcp.tool()
def load_pdf(file_path: str, pdf_id: Optional[str] = None) -> str:
    """Load a PDF file and extract its text content.
    
    Args:
        file_path: Path to the PDF file to load
        pdf_id: Unique identifier for this PDF (optional, will use filename if not provided)
    
    Returns:
        Success message with PDF details
    """
    if pdf_id is None:
        pdf_id = Path(file_path).stem
    
    if not Path(file_path).exists():
        return f"Error: File not found: {file_path}"
    
    try:
        # Use PyMuPDF for better text extraction
        doc = fitz.open(file_path)
        pages_text = []
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            pages_text.append({
                "page": page_num + 1,
                "text": text.strip()
            })
        
        doc.close()
        
        # Store in memory
        pdf_storage[pdf_id] = {
            "file_path": file_path,
            "pages": pages_text,
            "total_pages": len(pages_text),
            "total_chars": sum(len(p["text"]) for p in pages_text)
        }
        
        return f"Successfully loaded PDF '{pdf_id}' with {len(pages_text)} pages from {file_path}"
        
    except Exception as e:
        return f"Error loading PDF: {str(e)}"

@mcp.tool()
def get_pdf_content(pdf_id: str, pages: str = "1-3") -> str:
    """Get the actual text content from specific pages of a loaded PDF.
    
    Args:
        pdf_id: ID of the loaded PDF
        pages: Page range to extract (e.g., '1-3', '1', 'all')
    
    Returns:
        Text content from the specified pages
    """
    if pdf_id not in pdf_storage:
        return f"Error: PDF '{pdf_id}' not loaded. Use load_pdf first."
    
    pdf_data = pdf_storage[pdf_id]
    all_pages = pdf_data["pages"]
    
    # Parse page range
    if pages == "all":
        selected_pages = all_pages
    else:
        try:
            if "-" in pages:
                start, end = map(int, pages.split("-"))
                selected_pages = [p for p in all_pages if start <= p["page"] <= end]
            else:
                page_num = int(pages)
                selected_pages = [p for p in all_pages if p["page"] == page_num]
        except ValueError:
            return "Error: Invalid page range format. Use 'all', '5', or '1-10'"
    
    if not selected_pages:
        return f"No pages found for range '{pages}'"
    
    # Combine text from selected pages
    combined_text = ""
    for page_data in selected_pages:
        combined_text += f"\n--- Page {page_data['page']} ---\n"
        combined_text += page_data['text']
        combined_text += "\n"
    
    # Limit output length to avoid overwhelming the LLM
    if len(combined_text) > 8000:
        combined_text = combined_text[:8000] + "\n\n[Content truncated due to length...]"
    
    return combined_text

@mcp.tool()
def search_pdf_flexible(pdf_id: str, query: str, context_words: int = 50) -> str:
    """Search PDF with flexible matching including partial words and context.
    
    Args:
        pdf_id: ID of the loaded PDF to search
        query: Search terms (can be multiple words)
        context_words: Number of words to include around matches for context
    
    Returns:
        Search results with context around matches
    """
    if pdf_id not in pdf_storage:
        return f"Error: PDF '{pdf_id}' not loaded. Use load_pdf first."
    
    pdf_data = pdf_storage[pdf_id]
    pages = pdf_data["pages"]
    
    # Split query into individual terms for flexible matching
    query_terms = [term.lower().strip() for term in query.split() if len(term.strip()) > 2]
    
    if not query_terms:
        return "Error: Please provide search terms with at least 3 characters each."
    
    results = []
    
    for page_data in pages:
        text = page_data["text"]
        text_lower = text.lower()
        words = text.split()
        
        # Find matches for any of the query terms
        matches_found = []
        for i, word in enumerate(words):
            word_lower = word.lower()
            for term in query_terms:
                if term in word_lower:
                    # Extract context around the match
                    start_idx = max(0, i - context_words)
                    end_idx = min(len(words), i + context_words + 1)
                    context = " ".join(words[start_idx:end_idx])
                    
                    matches_found.append({
                        "term": term,
                        "context": context,
                        "word_position": i
                    })
                    break
        
        if matches_found:
            # Remove duplicate contexts
            unique_contexts = []
            seen_contexts = set()
            for match in matches_found:
                if match["context"] not in seen_contexts:
                    unique_contexts.append(match)
                    seen_contexts.add(match["context"])
            
            results.append({
                "page": page_data["page"],
                "matches": unique_contexts[:3]  # Limit to 3 unique contexts per page
            })
    
    if not results:
        return f"No matches found for any terms in '{query}' in PDF '{pdf_id}'"
    
    # Format results
    result_text = f"🔍 Found matches on {len(results)} pages for terms in '{query}':\n\n"
    for result in results:
        result_text += f"📄 Page {result['page']}:\n"
        for i, match in enumerate(result['matches'], 1):
            result_text += f"  {i}. ...{match['context']}...\n"
        result_text += "\n"
    
    return result_text

@mcp.tool()
def get_pdf_summary_content(pdf_id: str) -> str:
    """Get content from key sections likely to contain summary information (abstract, introduction, conclusion).
    
    Args:
        pdf_id: ID of the loaded PDF
    
    Returns:
        Text from abstract, introduction, and conclusion sections
    """
    if pdf_id not in pdf_storage:
        return f"Error: PDF '{pdf_id}' not loaded. Use load_pdf first."
    
    pdf_data = pdf_storage[pdf_id]
    pages = pdf_data["pages"]
    
    # Combine all text to search for sections
    all_text = ""
    for page_data in pages:
        all_text += f" PAGE_{page_data['page']} " + page_data["text"] + " "
    
    # Look for key sections
    sections_found = {}
    
    # Abstract section
    abstract_patterns = [
        r'(?i)(abstract[\s\n]*(?:[-–—][\s\n]*)?)(.*?)(?=\n\s*(?:introduction|keywords|1\.|1\s+introduction))',
        r'(?i)(abstract[\s\n]*)(.*?)(?=\n\s*\n|\n\s*[A-Z])',
    ]
    
    for pattern in abstract_patterns:
        match = re.search(pattern, all_text, re.DOTALL)
        if match and len(match.group(2).strip()) > 50:
            sections_found["Abstract"] = match.group(2).strip()[:1000]
            break
    
    # Introduction section (first page or two)
    intro_text = ""
    for page_data in pages[:3]:  # Check first 3 pages
        if any(word in page_data["text"].lower() for word in ["introduction", "background", "motivation"]):
            intro_text += page_data["text"] + " "
    
    if intro_text:
        sections_found["Introduction/Background"] = intro_text[:1500]
    
    # Conclusion section (last few pages)
    concl_text = ""
    for page_data in pages[-3:]:  # Check last 3 pages
        if any(word in page_data["text"].lower() for word in ["conclusion", "conclusions", "summary", "discussion"]):
            concl_text += page_data["text"] + " "
    
    if concl_text:
        sections_found["Conclusion/Summary"] = concl_text[:1500]
    
    # If no sections found, return first few pages
    if not sections_found:
        first_pages_text = ""
        for page_data in pages[:2]:
            first_pages_text += f"Page {page_data['page']}:\n{page_data['text']}\n\n"
        return f"No clear sections identified. Here are the first pages:\n\n{first_pages_text[:2000]}"
    
    # Format results
    result_text = f"📋 Key sections from PDF '{pdf_id}':\n\n"
    for section_name, content in sections_found.items():
        result_text += f"## {section_name}\n{content}\n\n"
    
    return result_text

# Keep the existing tools
@mcp.tool()
def query_pdf(pdf_id: str, query: str, page_range: str = "all") -> str:
    """Search and extract relevant text from a loaded PDF (legacy function - use search_pdf_flexible for better results).
    
    Args:
        pdf_id: ID of the loaded PDF to query
        query: Search query or question about the PDF content
        page_range: Page range to search (e.g., '1-5', 'all')
    
    Returns:
        Search results with matching text and page numbers
    """
    # Use the new flexible search function
    return search_pdf_flexible(pdf_id, query)

@mcp.tool()
def list_loaded_pdfs() -> str:
    """List all currently loaded PDFs with their basic information."""
    if not pdf_storage:
        return "No PDFs currently loaded."
    
    result = "📚 Loaded PDFs:\n\n"
    for pdf_id, data in pdf_storage.items():
        avg_chars = data['total_chars'] // data['total_pages'] if data['total_pages'] > 0 else 0
        result += f"• {pdf_id}:\n"
        result += f"  - Pages: {data['total_pages']}\n"
        result += f"  - File: {data['file_path']}\n"
        result += f"  - Avg chars/page: {avg_chars}\n\n"
    
    return result

@mcp.tool()
def get_pdf_info(pdf_id: str) -> str:
    """Get detailed metadata and information about a loaded PDF."""
    if pdf_id not in pdf_storage:
        return f"Error: PDF '{pdf_id}' not found. Available PDFs: {list(pdf_storage.keys())}"
    
    data = pdf_storage[pdf_id]
    avg_chars = data['total_chars'] // data['total_pages'] if data['total_pages'] > 0 else 0
    
    # Get a sample of content from first page
    first_page_preview = ""
    if data['pages']:
        preview_text = data['pages'][0]['text'][:200]
        first_page_preview = f"First page preview: {preview_text}..."
    
    info = f"""📋 PDF Information for '{pdf_id}':

    📁 File Path: {data['file_path']}
    📄 Total Pages: {data['total_pages']}
    📊 Total Characters: {data['total_chars']:,}
    📈 Average Characters per Page: {avg_chars:,}

    {first_page_preview}"""
    
    return info

@mcp.tool()
def extract_page_text(pdf_id: str, page_number: int) -> str:
    """Extract the full text content from a specific page."""
    if pdf_id not in pdf_storage:
        return f"Error: PDF '{pdf_id}' not loaded."
    
    pdf_data = pdf_storage[pdf_id]
    pages = pdf_data["pages"]
    
    # Find the page (convert from 1-indexed to 0-indexed)
    target_page = None
    for page in pages:
        if page["page"] == page_number:
            target_page = page
            break
    
    if target_page is None:
        return f"Error: Page {page_number} not found. PDF has {len(pages)} pages."
    
    return f"📄 Page {page_number} content:\n\n{target_page['text']}"

if __name__ == "__main__":
    mcp.run()