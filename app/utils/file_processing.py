import os
import json
import ast
import zipfile
import tarfile

try:
    import PyPDF2
    import docx
    HAS_DOC_SUPPORT = True
except ImportError:
    HAS_DOC_SUPPORT = False
    PyPDF2 = None
    docx = None

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'py', 'js', 'html', 'css', 'json', 'xml', 'cs', 'yaml', 'yml', 'md', 'sql', 'ipynb', 'zip', 'tar', 'tar.gz', 'tgz', 'rar', '7z'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_jupyter_notebook(notebook_content):
    """Process Jupyter notebook and extract code, markdown, and outputs"""
    try:
        notebook = json.loads(notebook_content)

        processed_content = "=== JUPYTER NOTEBOOK ANALYSIS ===\n\n"

        # Extract metadata
        if 'metadata' in notebook:
            metadata = notebook['metadata']
            if 'kernelspec' in metadata:
                kernel = metadata['kernelspec']
                processed_content += f"**Kernel:** {kernel.get('display_name', 'Unknown')} ({kernel.get('name', 'unknown')})\n"
            if 'language_info' in metadata:
                lang_info = metadata['language_info']
                processed_content += f"**Language:** {lang_info.get('name', 'Unknown')} v{lang_info.get('version', 'Unknown')}\n"

        processed_content += f"**Total Cells:** {len(notebook.get('cells', []))}\n\n"

        # Process cells
        code_cells = 0
        markdown_cells = 0

        for i, cell in enumerate(notebook.get('cells', []), 1):
            cell_type = cell.get('cell_type', 'unknown')
            source = ''.join(cell.get('source', []))

            if cell_type == 'code':
                code_cells += 1
                if source.strip():
                    processed_content += f"### Code Cell {i}\n```python\n{source}\n```\n"

                    # Include outputs if present
                    outputs = cell.get('outputs', [])
                    if outputs:
                        processed_content += "**Output:**\n"
                        for output in outputs:
                            if output.get('output_type') == 'stream':
                                stream_text = ''.join(output.get('text', []))
                                processed_content += f"```\n{stream_text}\n```\n"
                            elif output.get('output_type') == 'execute_result':
                                data = output.get('data', {})
                                if 'text/plain' in data:
                                    result_text = ''.join(data['text/plain'])
                                    processed_content += f"```\n{result_text}\n```\n"
                    processed_content += "\n"

            elif cell_type == 'markdown':
                markdown_cells += 1
                if source.strip():
                    processed_content += f"### Markdown Cell {i}\n{source}\n\n"

        processed_content += f"\n**Summary:** {code_cells} code cells, {markdown_cells} markdown cells\n"

        return processed_content

    except Exception as e:
        return f"[Jupyter notebook processing error: {str(e)}]"

def process_archive_file(file_path, filename):
    """Process archive files (zip, tar, etc.) and extract file list with content preview"""
    try:
        file_extension = os.path.splitext(filename)[1].lower()
        second_ext = os.path.splitext(os.path.splitext(filename)[0])[1].lower()

        processed_content = f"=== ARCHIVE ANALYSIS: {filename} ===\n\n"

        files_list = []
        total_files = 0

        if file_extension == '.zip':
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                total_files = len(file_list)

                for file_name in file_list[:20]:  # Limit to first 20 files
                    file_info = zip_ref.getinfo(file_name)
                    files_list.append({
                        'name': file_name,
                        'size': file_info.file_size,
                        'is_dir': file_name.endswith('/'),
                        'compressed_size': file_info.compress_size
                    })

                # Try to extract and preview small text files
                for file_name in file_list[:5]:  # Preview first 5 files
                    if (not file_name.endswith('/') and 
                        any(file_name.lower().endswith(ext) for ext in ['.py', '.js', '.txt', '.md', '.json', '.yaml', '.yml']) and
                        zip_ref.getinfo(file_name).file_size < 10000):  # Less than 10KB

                        try:
                            with zip_ref.open(file_name) as f:
                                content = f.read().decode('utf-8')[:500]
                                processed_content += f"\n### Preview: {file_name}\n```\n{content}{'...' if len(content) >= 500 else ''}\n```\n"
                        except:
                            continue

        elif file_extension in ['.tar', '.tgz'] or second_ext == '.tar':
            mode = 'r:gz' if file_extension in ['.tgz'] or second_ext == '.tar' else 'r'
            with tarfile.open(file_path, mode) as tar_ref:
                members = tar_ref.getmembers()
                total_files = len(members)

                for member in members[:20]:  # Limit to first 20 files
                    files_list.append({
                        'name': member.name,
                        'size': member.size,
                        'is_dir': member.isdir(),
                        'type': 'directory' if member.isdir() else 'file'
                    })

                # Try to extract and preview small text files
                for member in members[:5]:  # Preview first 5 files
                    if (member.isfile() and 
                        any(member.name.lower().endswith(ext) for ext in ['.py', '.js', '.txt', '.md', '.json', '.yaml', '.yml']) and
                        member.size < 10000):  # Less than 10KB

                        try:
                            f = tar_ref.extractfile(member)
                            if f:
                                content = f.read().decode('utf-8')[:500]
                                processed_content += f"\n### Preview: {member.name}\n```\n{content}{'...' if len(content) >= 500 else ''}\n```\n"
                        except:
                            continue

        # Build file list summary
        processed_content += f"**Total Files:** {total_files}\n"
        processed_content += f"**Showing:** {min(len(files_list), 20)} files\n\n"

        processed_content += "**File Structure:**\n```\n"
        for file_info in files_list:
            size_str = f" ({file_info['size']} bytes)" if not file_info.get('is_dir', False) else " (directory)"
            processed_content += f"{file_info['name']}{size_str}\n"

        if total_files > 20:
            processed_content += f"... and {total_files - 20} more files\n"

        processed_content += "```\n"

        return processed_content

    except Exception as e:
        return f"[Archive processing error: {str(e)}]"

def analyze_code_structure(code_content, file_extension):
    """Analyze code structure and extract meaningful information"""
    analysis = {
        'functions': [],
        'classes': [],
        'imports': [],
        'complexity_score': 0,
        'line_count': len(code_content.split('\n'))
    }

    try:
        if file_extension in ['.py']:
            tree = ast.parse(code_content)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    analysis['functions'].append({
                        'name': node.name,
                        'line': node.lineno,
                        'args': [arg.arg for arg in node.args.args]
                    })
                elif isinstance(node, ast.ClassDef):
                    analysis['classes'].append({
                        'name': node.name,
                        'line': node.lineno
                    })
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        analysis['imports'].append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        analysis['imports'].append(f"from {node.module}")

        # Simple complexity estimation
        analysis['complexity_score'] = len(analysis['functions']) + len(analysis['classes']) * 2

    except Exception as e:
        analysis['error'] = f"Code analysis error: {str(e)}"

    return analysis

def process_uploaded_file(file_path):
    """Enhanced file processing with code analysis and better content extraction"""
    filename = os.path.basename(file_path)
    file_extension = os.path.splitext(filename)[1].lower()

    try:
        content = ""

        # Handle different file types
        if file_extension == '.pdf' and HAS_DOC_SUPPORT and PyPDF2:
            try:
                with open(file_path, 'rb') as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    content = ""
                    for page in pdf_reader.pages:
                        content += page.extract_text() + "\n"
            except Exception as e:
                content = f"[PDF processing error: {str(e)}]"

        elif file_extension in ['.docx', '.doc'] and HAS_DOC_SUPPORT and docx:
            try:
                doc = docx.Document(file_path)
                content = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            except Exception as e:
                content = f"[Document processing error: {str(e)}]"

        elif file_extension == '.ipynb':
            # Jupyter Notebook processing
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    notebook_content = f.read()
                content = process_jupyter_notebook(notebook_content)
            except Exception as e:
                content = f"[Jupyter notebook processing error: {str(e)}]"

        elif file_extension in ['.zip', '.tar', '.tgz'] or filename.lower().endswith('.tar.gz'):
            # Archive file processing
            content = process_archive_file(file_path, filename)

        else:
            # Text-based files
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                try:
                    with open(file_path, 'r', encoding='latin-1') as f:
                        content = f.read()
                except Exception as e:
                    return f"[Binary file - could not read: {str(e)}]"

        # Enhanced processing for code files
        code_analysis = None
        if file_extension in ['.py', '.js', '.cs', '.java', '.cpp', '.c', '.h']:
            code_analysis = analyze_code_structure(content, file_extension)

            # Add analysis summary to content
            if code_analysis and 'error' not in code_analysis:
                analysis_summary = f"\n\n--- CODE ANALYSIS ---\n"
                analysis_summary += f"File: {filename}\n"
                analysis_summary += f"Lines: {code_analysis['line_count']}\n"
                analysis_summary += f"Functions: {len(code_analysis['functions'])}\n"
                analysis_summary += f"Classes: {len(code_analysis['classes'])}\n"
                analysis_summary += f"Imports: {len(code_analysis['imports'])}\n"
                analysis_summary += f"Complexity Score: {code_analysis['complexity_score']}\n"

                if code_analysis['functions']:
                    analysis_summary += f"Function Names: {', '.join([f['name'] for f in code_analysis['functions']])}\n"

                content += analysis_summary

        return content, code_analysis

    except Exception as e:
        return f"[Error processing {filename}: {str(e)}]", None
