import os
import json
import uuid
from pathlib import Path
import chromadb
from chromadb.config import Settings
import dotenv

dotenv.load_dotenv()

# We will use the Google GenAI embedding function if an API key is available,
# otherwise we'll fallback to a default sentence-transformers model (built-in ChromaDB).
# For the prototype, standard ChromaDB sentence-transformers is fine if Google API isn't set yet.

RAW_DIR = Path("data/raw")
CHROMA_DIR = Path("data/chroma_db")

def parse_markdown(content: str):
    """Parses markdown with simple YAML frontmatter."""
    lines = content.split('\n')
    if lines[0].strip() == '---':
        end_idx = 1
        while end_idx < len(lines) and lines[end_idx].strip() != '---':
            end_idx += 1
        
        frontmatter = lines[1:end_idx]
        body = '\n'.join(lines[end_idx+1:]).strip()
        
        metadata = {}
        for line in frontmatter:
            if ':' in line:
                key, val = line.split(':', 1)
                val = val.strip()
                if val == 'None' or val == 'null':
                    val = None
                metadata[key.strip()] = val
        return body, metadata
    return content, {}

def ingest_data():
    print("Starting ingestion pipeline...")
    
    # Initialize ChromaDB client
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    
    # Check if we should use Google GenAI embeddings
    api_key = os.getenv("GOOGLE_API_KEY")
    embedding_function = None
    
    if api_key:
        try:
            from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            
            class LangchainGoogleEmbeddingFunction(EmbeddingFunction):
                def __init__(self, key: str):
                    self.embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-2", google_api_key=key)
                    
                def __call__(self, input: Documents) -> Embeddings:
                    return self.embeddings.embed_documents(list(input))
                    
            print("Using Langchain Google GenAI embedding function.")
            embedding_function = LangchainGoogleEmbeddingFunction(key=api_key)
        except ImportError:
            print("Langchain Google GenAI embedding function not found. Falling back to default.")
            pass
    # Create or get collection
    collection_name = "novacart_docs"
    try:
        client.delete_collection(name=collection_name)
    except Exception:
        pass
        
    if embedding_function:
        collection = client.create_collection(name=collection_name, embedding_function=embedding_function)
    else:
        # Default all-MiniLM-L6-v2
        collection = client.create_collection(name=collection_name)

    documents = []
    metadatas = []
    ids = []
    
    for filepath in RAW_DIR.glob("*"):
        if filepath.is_file():
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                
            doc_text = ""
            doc_meta = {}
            
            if filepath.suffix == '.json':
                data = json.loads(content)
                # content can be a string or we serialize the original json dict
                if isinstance(data.get("content"), dict):
                    doc_text = json.dumps(data["content"])
                else:
                    doc_text = str(data.get("content", ""))
                doc_meta = data.get("metadata", {})
                
            elif filepath.suffix == '.md':
                doc_text, doc_meta = parse_markdown(content)
                
            # Filter out None values from metadata as ChromaDB doesn't allow None
            clean_meta = {k: v for k, v in doc_meta.items() if v is not None}
            
            # Combine metadata and content for better semantic search retrieval
            meta_str = ", ".join(f"{k}: {v}" for k, v in clean_meta.items())
            doc_text_with_meta = f"[{meta_str}]\n{doc_text}"
            
            documents.append(doc_text_with_meta)
            metadatas.append(clean_meta)
            ids.append(clean_meta.get("doc_id", str(uuid.uuid4())))
            
    if documents:
        print(f"Adding {len(documents)} documents to ChromaDB...")
        # Add in batches if necessary, but 20-30 files is small enough for one call
        collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        print("Ingestion complete!")
    else:
        print("No documents found to ingest.")

if __name__ == "__main__":
    ingest_data()
