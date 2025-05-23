"""
Main RAG pipeline orchestrating all components with Supabase integration.
"""

import os
import time
import uuid
import hashlib
from typing import List, Dict, Tuple, Optional, Union, BinaryIO
import openai
from openai import OpenAI
from dotenv import load_dotenv

from models.data_models import Document
from components.semantic_cache import SemanticCache
from components.vector_store import VectorStore
from components.router import AgenticRouter
from components.web_search import BraveWebSearcher
from utils.logging_utils import logger

# Load environment variables
load_dotenv()


class RAGPipeline:
    """Main RAG pipeline orchestrating all components with Supabase integration"""

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        embedding_client_type: str = "nomic_ai",
    ):
        # Initialize components with Supabase tables
        self.vector_store = VectorStore(
            table_name="documents", embedding_client_type=embedding_client_type
        )
        self.cache = SemanticCache(
            table_name="cache_entries", embedding_client_type=embedding_client_type
        )
        self.router = AgenticRouter()
        self.web_searcher = BraveWebSearcher()

        # Initialize OpenAI
        if openai_api_key:
            openai.api_key = openai_api_key
        else:
            openai.api_key = os.getenv("OPENAI_API_KEY")

        # Initialize OpenAI client
        self.openai_client = OpenAI(api_key=openai.api_key)

        # Load sample data if the vector store is empty
        self._load_sample_data_if_needed()

    def _load_sample_data_if_needed(self):
        """Load sample 10-K data if the vector store is empty"""
        # In a real application, you would check if data exists first
        # For simplicity, we'll always load the sample data
        sample_documents = [
            Document(
                id="AAPL_2023_10K_1",
                content="Apple Inc. reported total net sales of $394.3 billion for fiscal 2023, compared to $365.8 billion for fiscal 2022. iPhone sales represented $200.6 billion of total revenue.",
                metadata={
                    "company": "Apple Inc.",
                    "filing_type": "10-K",
                    "year": 2023,
                    "section": "Financial Performance",
                },
            ),
            Document(
                id="MSFT_2023_10K_1",
                content="Microsoft Corporation's revenue was $211.9 billion for fiscal year 2023, an increase of 7% compared to fiscal year 2022. Azure and other cloud services revenue grew 27%.",
                metadata={
                    "company": "Microsoft Corporation",
                    "filing_type": "10-K",
                    "year": 2023,
                    "section": "Revenue",
                },
            ),
            Document(
                id="GOOGL_2023_10K_1",
                content="Alphabet Inc.'s revenues were $307.4 billion for the year ended December 31, 2023, compared to $282.8 billion in the prior year. Google Search revenues were $175.0 billion.",
                metadata={
                    "company": "Alphabet Inc.",
                    "filing_type": "10-K",
                    "year": 2023,
                    "section": "Business Overview",
                },
            ),
            Document(
                id="TSLA_2023_10K_1",
                content="Tesla, Inc. automotive revenues were $82.4 billion for the year ended December 31, 2023, compared to $71.5 billion for the year ended December 31, 2022.",
                metadata={
                    "company": "Tesla Inc.",
                    "filing_type": "10-K",
                    "year": 2023,
                    "section": "Automotive Sales",
                },
            ),
            Document(
                id="NVDA_2023_10K_1",
                content="NVIDIA Corporation's revenue for fiscal 2024 was a record $60.9 billion, up 126% from the previous year. Data Center revenue was $47.5 billion, up 217% from the prior year.",
                metadata={
                    "company": "NVIDIA Corporation",
                    "filing_type": "10-K",
                    "year": 2024,
                    "section": "Financial Results",
                },
            ),
        ]

        try:
            self.vector_store.add_documents(sample_documents)
            logger.info("Sample data loaded into Supabase vector store")
        except Exception as e:
            logger.error(f"Error loading sample data: {str(e)}")

    def _clean_text(self, text: str) -> str:
        """Clean text by removing excessive whitespace and fixing common formatting issues"""
        import re

        # First, check if there are any vertically stacked characters
        # This pattern looks for single characters separated by newlines or excessive spaces
        vertical_text_pattern = r"(\d+\.?\d*)\s*\n?\s*([a-z])\s*\n?\s*([a-z])\s*\n?\s*([a-z])\s*\n?\s*([a-z])\s*\n?\s*([a-z])\s*\n?\s*([a-z])\s*\n?\s*([a-z])"
        if re.search(vertical_text_pattern, text, re.IGNORECASE | re.DOTALL):
            # If vertical text is detected, first join all lines and normalize spaces
            text = re.sub(r"\s+", " ", text)

        # Replace multiple spaces and newlines with a single space
        text = re.sub(r"\s+", " ", text)

        # Fix broken numbers with vertical text (e.g., "60.9 b i l l i o n")
        text = re.sub(
            r"(\d+\.?\d*)\s+b\s+i\s+l\s+l\s+i\s+o\s+n",
            r"\1 billion",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"(\d+\.?\d*)\s+m\s+i\s+l\s+l\s+i\s+o\s+n",
            r"\1 million",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"(\d+\.?\d*)\s+t\s+r\s+i\s+l\s+l\s+i\s+o\s+n",
            r"\1 trillion",
            text,
            flags=re.IGNORECASE,
        )

        # Fix broken numbers with no spaces (e.g., "60.9billion")
        text = re.sub(r"(\d+\.?\d*)billion", r"\1 billion", text, flags=re.IGNORECASE)
        text = re.sub(r"(\d+\.?\d*)million", r"\1 million", text, flags=re.IGNORECASE)
        text = re.sub(r"(\d+\.?\d*)trillion", r"\1 trillion", text, flags=re.IGNORECASE)

        # Fix broken phrases like "whichwasup126"
        text = re.sub(
            r"which\s*was\s*up\s*(\d+\.?\d*)",
            r"which was up \1%",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"whichwasup(\d+\.?\d*)", r"which was up \1%", text, flags=re.IGNORECASE
        )

        # Fix broken percentages
        text = re.sub(r"(\d+)\s*\.\s*(\d+)\s*%", r"\1.\2%", text)

        # Fix specific patterns seen in examples
        text = re.sub(
            r"(\d+\.?\d*)\s*billion\s*,\s*which\s*was\s*up\s*(\d+\.?\d*)(\d+\.?\d*)",
            r"\1 billion, which was up \2% from \3 billion",
            text,
        )

        # Fix broken sentences
        text = re.sub(r"([a-z])\.([a-z])", r"\1. \2", text, flags=re.IGNORECASE)

        # Final cleanup of any remaining issues
        text = re.sub(
            r"(\d+)b(\d+)i(\d+)l(\d+)l(\d+)i(\d+)o(\d+)n",
            r"\1\2\3\4\5\6\7 billion",
            text,
        )
        text = re.sub(r"billion,whichwasup", r"billion, which was up ", text)

        return text.strip()

    def _generate_answer(
        self,
        query: str,
        context_docs: List[Tuple[Document, float]],
        use_web: bool = False,
        web_results: str = "",
    ) -> str:
        """Generate answer using retrieved context and GPT-4.1 Mini"""

        # Prepare context
        context_parts = []
        if context_docs:
            for doc, score in context_docs:
                doc_title = doc.metadata.get(
                    "title", doc.metadata.get("company", "Unknown")
                )
                context_parts.append(f"Document ({doc_title}): {doc.content}")

        if web_results:
            # Clean the web results before adding to context
            cleaned_web_results = self._clean_text(web_results)
            context_parts.append(f"Web Information: {cleaned_web_results}")

        context = "\n\n".join(context_parts)

        # If no context is found, return a simple message
        if not context:
            return "I couldn't find relevant information to answer your question."

        try:
            # Use OpenAI API to generate a response with GPT-4o
            answer = self._generate_openai_answer(query, context)
            # Clean the answer text
            return self._clean_text(answer)
        except Exception as e:
            logger.error(f"Error generating answer with OpenAI: {str(e)}")
            # Fallback to mock answer if OpenAI API fails
            fallback = f"""Based on the available information:

{context}

Analysis: The query "{query}" relates to financial and corporate information. The retrieved documents provide relevant context.

Answer: {self._generate_mock_answer(query, context_docs, web_results)}

Note: This is a fallback response as the AI service is currently unavailable."""
            return self._clean_text(fallback)

    def _generate_openai_answer(self, query: str, context: str) -> str:
        """Generate an answer using OpenAI's GPT-4o model with the Chat Completions API"""
        try:
            # Check if OpenAI API key is valid
            if not openai.api_key:
                logger.warning(
                    "Missing OpenAI API key. Using fallback answer generation."
                )
                return self._generate_enhanced_mock_answer(query, context)

            # Log the type of API key being used
            if openai.api_key.startswith("sk-proj-"):
                logger.info("Using project-specific OpenAI API key (sk-proj-)")
            else:
                logger.info("Using standard OpenAI API key (sk-)")

            # We'll use the Chat Completions API with messages instead of a single prompt

            # Call the OpenAI API with GPT-4o
            try:
                # Create messages for Chat Completions API
                messages = [
                    {
                        "role": "system",
                        "content": "You are a helpful financial research assistant.",
                    },
                    {
                        "role": "user",
                        "content": f"Context information:\n\n{context}\n\nQuestion: {query}",
                    },
                ]

                response = self.openai_client.chat.completions.create(
                    model="gpt-4o",  # Using the GPT-4o model
                    messages=messages,
                    temperature=0.3,  # Lower temperature for more factual responses
                    max_tokens=1000,
                )

                # Extract and return the generated answer
                answer = response.choices[0].message.content.strip()
            except Exception as e:
                logger.error(
                    f"Error in OpenAI Chat Completions API call with gpt-4o: {str(e)}"
                )
                # Try fallback to gpt-3.5-turbo
                logger.info("Falling back to gpt-3.5-turbo model")

                # Create messages for Chat Completions API
                messages = [
                    {
                        "role": "system",
                        "content": "You are a helpful financial research assistant.",
                    },
                    {
                        "role": "user",
                        "content": f"Context information:\n\n{context}\n\nQuestion: {query}",
                    },
                ]

                # Call the Chat Completions API with gpt-3.5-turbo as fallback
                response = self.openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=messages,
                    temperature=0.3,
                    max_tokens=1000,
                )

                answer = response.choices[0].message.content.strip()
            return answer

        except Exception as e:
            logger.error(f"Error in OpenAI API call: {str(e)}")
            # Use enhanced mock answer instead of raising an exception
            return self._generate_enhanced_mock_answer(query, context)

    def _generate_enhanced_mock_answer(self, query: str, context: str) -> str:
        """Generate a more sophisticated mock answer when OpenAI API is unavailable"""
        # Extract key information from context
        context_lines = context.split("\n")
        relevant_facts = []

        for line in context_lines:
            if (
                line
                and not line.startswith("Document")
                and not line.startswith("Web Information")
            ):
                # Look for sentences with numbers, dates, or key terms
                if any(
                    term in line.lower()
                    for term in [
                        "$",
                        "%",
                        "billion",
                        "million",
                        "revenue",
                        "sales",
                        "growth",
                        "increase",
                        "decrease",
                    ]
                ):
                    relevant_facts.append(line.strip())

        # Generate a structured answer
        answer_parts = []
        answer_parts.append(
            f"Based on the provided information, I can address your question about '{query}'."
        )

        if relevant_facts:
            answer_parts.append("\nKey facts from the documents:")
            for i, fact in enumerate(relevant_facts[:3], 1):  # Limit to top 3 facts
                answer_parts.append(f"{i}. {fact}")

        answer_parts.append(
            "\nNote: This is a generated response based on the retrieved documents. For more detailed analysis, please ensure your OpenAI API key is correctly configured."
        )

        return "\n".join(answer_parts)

    def _generate_mock_answer(
        self, query: str, docs: List[Tuple[Document, float]], web_results: str
    ) -> str:
        """Generate a mock answer as fallback if the OpenAI API fails"""
        if "revenue" in query.lower() or "sales" in query.lower():
            if docs:
                company = docs[0][0].metadata.get("company", "the company")
                return f"According to the latest filings, {company} has shown strong revenue performance as detailed in the retrieved documents."

        if "nvidia" in query.lower() and web_results:
            return "NVIDIA has demonstrated exceptional growth, particularly in data center and AI-related revenue streams."

        return "Based on the retrieved information, here's what I found relevant to your query."

    def search(self, query: str, allow_web_search: bool = False) -> Dict:
        """Main search function"""
        start_time = time.time()

        # Check cache first
        cached_response, cache_hit = self.cache.get(query)
        cache_debug = {"query": query}
        if cache_hit:
            return {
                "answer": cached_response,
                "sources": [],
                "cache_hit": True,
                "response_time": time.time() - start_time,
                "routing_decision": "cache",
                "web_search_used": False,
                "cache_debug": cache_debug,
            }

        # Route query
        routing_decision = self.router.route_query(query)
        web_results = ""

        # Always search local documents first
        retrieved_docs = self.vector_store.search(query, top_k=5)

        # Check if we found any relevant documents
        has_relevant_docs = False
        if retrieved_docs:
            # Consider a document relevant if its similarity score is above 0.7
            has_relevant_docs = any(score > 0.7 for _, score in retrieved_docs)

        # Check if query contains a year
        import re

        years_in_query = re.findall(r"\b(19\d\d|20\d\d)\b", query)
        contains_recent_year = False
        if years_in_query:
            # Get current year
            import datetime

            current_year = datetime.datetime.now().year
            # Check if any year in query is recent (current year, last year, or next year)
            contains_recent_year = any(
                int(year) >= current_year - 1 for year in years_in_query
            )
            logger.info(
                f"Years found in query: {years_in_query}, contains recent year: {contains_recent_year}"
            )

        # Handle web search if needed and allowed
        if allow_web_search and (
            routing_decision == "web_search"  # Router suggests web search
            or (
                not has_relevant_docs and contains_recent_year
            )  # No relevant docs and query is about recent years
        ):
            logger.info(
                f"Using web search. Routing decision: {routing_decision}, Has relevant docs: {has_relevant_docs}"
            )
            web_results = self.web_searcher.search(query)

        # Generate answer
        answer = self._generate_answer(
            query, retrieved_docs, allow_web_search, web_results
        )

        # Cache the response
        self.cache.put(query, answer)

        response_time = time.time() - start_time

        return {
            "answer": answer,
            "sources": [
                {
                    "content": doc.content[:200] + "...",
                    "metadata": doc.metadata,
                    "score": float(score),
                }
                for doc, score in retrieved_docs
            ],
            "cache_hit": False,
            "response_time": response_time,
            "routing_decision": routing_decision,
            "web_search_used": bool(
                web_results
            ),  # True if web search was actually used
            "web_results": web_results if web_results else None,
            "cache_debug": cache_debug,
        }

    def upload_text_document(self, content: str, metadata: Dict = None) -> str:
        """
        Upload a text document to the vector store

        Args:
            content: The text content of the document
            metadata: Optional metadata for the document

        Returns:
            The ID of the uploaded document
        """
        if metadata is None:
            metadata = {}

        # Generate a unique ID for the document
        doc_id = f"doc_{uuid.uuid4().hex[:10]}"

        # Create a Document object
        document = Document(id=doc_id, content=content, metadata=metadata)

        # Add the document to the vector store
        try:
            self.vector_store.add_documents([document])
            logger.info(f"Document uploaded with ID: {doc_id}")
            return doc_id
        except Exception as e:
            logger.error(f"Error uploading document: {str(e)}")
            raise

    def upload_file(
        self,
        file: BinaryIO,
        file_name: str,
        file_type: str = None,
        metadata: Dict = None,
    ) -> str:
        """
        Upload a file to the vector store

        Args:
            file: The file object (from Streamlit or other source)
            file_name: The name of the file
            file_type: The MIME type of the file (optional)
            metadata: Optional metadata for the document

        Returns:
            The ID of the uploaded document or a list of IDs if the file was split into chunks
        """
        if metadata is None:
            metadata = {}

        # Add file metadata
        metadata.update(
            {"file_name": file_name, "file_type": file_type, "upload_time": time.time()}
        )

        # Determine file type if not provided
        if not file_type:
            if file_name.endswith(".pdf"):
                file_type = "application/pdf"
            elif file_name.endswith((".doc", ".docx")):
                file_type = "application/msword"
            elif file_name.endswith(".txt"):
                file_type = "text/plain"

        # Make a copy of the file content for processing
        file_content = file.read()
        file.seek(0)  # Reset file pointer for further processing

        # Special handling for PDF files
        if file_type == "application/pdf":
            try:
                import PyPDF2
                import io

                # Create a PDF reader object
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_content))

                # Get the number of pages
                num_pages = len(pdf_reader.pages)
                logger.info(f"PDF has {num_pages} pages: {file_name}")

                # For large PDFs, split into chunks by page
                if num_pages > 5:  # Threshold for splitting
                    logger.info(f"Splitting large PDF into {num_pages} chunks")
                    doc_ids = []

                    # Process each page as a separate document
                    for page_num in range(num_pages):
                        page = pdf_reader.pages[page_num]
                        page_text = page.extract_text()

                        if not page_text:
                            continue  # Skip empty pages

                        # Create page-specific metadata
                        page_metadata = metadata.copy()
                        page_metadata.update(
                            {
                                "page_number": page_num + 1,
                                "total_pages": num_pages,
                                "content_type": "pdf_page",
                            }
                        )

                        # Generate a unique ID for this page
                        page_hash = hashlib.md5(page_text.encode()).hexdigest()[:10]
                        page_doc_id = f"file_{page_hash}_p{page_num + 1}"

                        # Create a Document object for this page
                        page_document = Document(
                            id=page_doc_id,
                            content=f"[Page {page_num + 1} of {num_pages}] {page_text}",
                            metadata=page_metadata,
                        )

                        # Add the page document to the vector store
                        self.vector_store.add_documents([page_document])
                        doc_ids.append(page_doc_id)

                    logger.info(f"PDF split into {len(doc_ids)} documents")
                    return doc_ids

                # For smaller PDFs, continue with normal processing
                file.seek(0)  # Reset file pointer
            except Exception as e:
                logger.error(f"Error processing PDF for chunking: {str(e)}")
                # Continue with normal processing if PDF chunking fails
                file.seek(0)  # Reset file pointer

        # Standard processing for all other files or small PDFs
        # Read the file content
        content = self._extract_text_from_file(file, file_name, file_type)

        # Generate a file-specific ID based on content hash
        content_hash = hashlib.md5(content.encode()).hexdigest()[:10]
        doc_id = f"file_{content_hash}"

        # Create a Document object
        document = Document(id=doc_id, content=content, metadata=metadata)

        # Add the document to the vector store
        try:
            self.vector_store.add_documents([document])
            logger.info(f"File uploaded with ID: {doc_id}")
            return doc_id
        except Exception as e:
            logger.error(f"Error uploading file: {str(e)}")
            raise

    def _extract_text_from_file(
        self, file: BinaryIO, file_name: str, file_type: str = None
    ) -> str:
        """
        Extract text from a file based on its type

        Args:
            file: The file object
            file_name: The name of the file
            file_type: The MIME type of the file (optional)

        Returns:
            The extracted text content
        """
        # Determine file type if not provided
        if not file_type:
            if file_name.endswith(".txt"):
                file_type = "text/plain"
            elif file_name.endswith(".pdf"):
                file_type = "application/pdf"
            elif file_name.endswith((".doc", ".docx")):
                file_type = "application/msword"
            else:
                file_type = "text/plain"  # Default to text

        # Extract text based on file type
        if file_type == "text/plain":
            # For text files, just read the content
            content = file.read().decode("utf-8")
        elif file_type == "application/pdf":
            # Use PyPDF2 to extract text from PDF
            try:
                import PyPDF2
                import io

                # Create a PDF reader object
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(file.read()))

                # Get the number of pages
                num_pages = len(pdf_reader.pages)
                logger.info(f"PDF has {num_pages} pages: {file_name}")

                # Extract text from each page
                page_texts = []
                for page_num in range(num_pages):
                    page = pdf_reader.pages[page_num]
                    page_text = page.extract_text()
                    if page_text:
                        page_texts.append(f"[Page {page_num + 1}] {page_text}")

                # Combine all page texts
                if page_texts:
                    content = "\n\n".join(page_texts)
                else:
                    content = f"No text could be extracted from PDF: {file_name}"
                    logger.warning(f"No text extracted from PDF: {file_name}")
            except Exception as e:
                content = (
                    f"Error extracting text from PDF: {file_name}. Error: {str(e)}"
                )
                logger.error(
                    f"Error extracting text from PDF: {file_name}. Error: {str(e)}"
                )
        elif file_type.startswith("application/msword"):
            # For Word documents, we would use a Word extraction library
            # This is a placeholder - in a real implementation, use python-docx, etc.
            content = f"Word document extraction not implemented. Filename: {file_name}"
            logger.warning("Word document extraction not implemented")
        else:
            # For unknown types, just try to read as text
            try:
                content = file.read().decode("utf-8")
            except UnicodeDecodeError:
                content = f"Could not extract text from file: {file_name}"
                logger.error(f"Could not extract text from file: {file_name}")

        return content

    def get_all_documents(self, limit: int = 100) -> List[Dict]:
        """
        Get all documents in the vector store

        Args:
            limit: Maximum number of documents to return

        Returns:
            List of documents with metadata
        """
        try:
            # Get documents from the vector store
            documents = self.vector_store.get_all_documents(limit)

            # Convert to a simplified format for display
            result = []
            for doc in documents:
                # Truncate content for display
                display_content = (
                    doc.content[:200] + "..." if len(doc.content) > 200 else doc.content
                )

                result.append(
                    {
                        "id": doc.id,
                        "content": display_content,
                        "metadata": doc.metadata,
                        "full_content": doc.content,  # Include full content for potential display
                    }
                )

            return result

        except Exception as e:
            logger.error(f"Error getting documents: {str(e)}")
            return []
