# Overview

Teyra is an AI-powered chat assistant application built with Flask. It provides an interactive web interface for users to have conversations with AI, featuring document upload capabilities, chat history persistence, and optional vector database support for enhanced AI capabilities. The application includes a modern dark theme UI with support for code highlighting and diagram rendering.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Frontend Architecture
- **Technology**: HTML5, CSS3, JavaScript with modern UI components
- **Styling**: Custom "Teyra Theme" CSS framework with dark space-themed design using CSS custom properties
- **Libraries**: Font Awesome for icons, Prism.js for code syntax highlighting, Mermaid.js for diagram rendering
- **Layout**: Responsive design with sidebar navigation and main chat interface
- **Theme System**: CSS custom properties enabling consistent color scheme and theming

## Backend Architecture
- **Framework**: Flask (Python) with session-based state management
- **API Design**: RESTful endpoints with JSON responses for chat interactions
- **File Handling**: Secure file upload system with support for PDF and DOCX documents
- **Session Management**: Flask sessions for maintaining user state across requests
- **Error Handling**: Graceful degradation for optional dependencies

## Data Storage Solutions
- **Primary Database**: SQLite for chat history persistence
- **Vector Database**: Optional FAISS integration for semantic search capabilities
- **File Storage**: Local filesystem storage for uploaded documents
- **Session Storage**: Server-side session management via Flask

## Authentication and Authorization
- **Session Security**: UUID-based secret key generation for session encryption
- **File Security**: Werkzeug secure filename handling to prevent path traversal attacks
- **Environment Variables**: Secure API key management through environment variables

## AI Integration Architecture
- **Primary AI**: OpenAI API integration for chat completions
- **Document Processing**: PyPDF2 and python-docx for extracting text from uploaded files
- **Vector Search**: Optional sentence-transformers for text embedding and semantic search
- **Streaming**: Support for real-time streaming responses from AI models

# External Dependencies

## Core Dependencies
- **Flask**: Web framework for HTTP request handling and routing
- **OpenAI**: Official OpenAI Python client for GPT model interactions
- **SQLite3**: Built-in Python database driver for local data persistence

## Optional Enhanced Features
- **sentence-transformers**: Hugging Face library for text embeddings and semantic search
- **faiss-cpu**: Facebook's vector similarity search library for efficient vector operations
- **PyPDF2**: PDF document parsing and text extraction
- **python-docx**: Microsoft Word document processing

## Frontend Libraries
- **Font Awesome 6.0.0**: Icon library via CDN for UI elements
- **Prism.js 1.29.0**: Syntax highlighting library for code blocks
- **Mermaid.js**: Diagram and flowchart rendering library

## Development and Security
- **Werkzeug**: WSGI utilities for secure file handling and development server
- **NumPy**: Scientific computing library (dependency of sentence-transformers)

## Environment Configuration
- **OPENAI_API_KEY**: Required environment variable for AI service authentication
- **FLASK_SECRET_KEY**: Optional environment variable for session security (auto-generated if not provided)