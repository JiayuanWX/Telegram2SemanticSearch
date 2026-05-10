import json
import os
from qdrant_client import QdrantClient
from qdrant_client.http import models
from sentence_transformers import SentenceTransformer

def ingest_to_qdrant():
    backup_dir = "backup"
    parsed_file = os.path.join(backup_dir, "parsed.json")
    
    if not os.path.exists(parsed_file):
        print(f"File {parsed_file} not found. Run parse_urls.py first.")
        return

    # 1. Load entries from parsed.json
    with open(parsed_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    if not data:
        print("No data found in parsed.json.")
        return

    print(f"Loaded {len(data)} entries from {parsed_file}")

    # 2. Download BGE-small (cached after first run)
    # BAAI/bge-small-en-v1.5 produces 384-dim embeddings
    print("Loading BGE model...")
    model = SentenceTransformer('BAAI/bge-small-en-v1.5')

    # 3. Create Qdrant collection
    # Connecting to the Docker container at localhost:6333
    client = QdrantClient("localhost", port=6333)
    collection_name = "tg_urls"

    print(f"Ensuring collection '{collection_name}' exists in Docker Qdrant...")
    if client.collection_exists(collection_name):
        client.delete_collection(collection_name)
    
    client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
    )

    # 4. Generate embeddings and prepare points
    print("Generating embeddings and preparing points...")
    points = []
    
    for i, entry in enumerate(data):
        url = entry.get("original_url") or entry.get("fetched_url")
        date = entry.get("date", "")
        description = entry.get("description", "")
        
        # Text to embed: (URL + date + description)
        text_to_embed = f"URL: {url} | Date: {date} | Description: {description}"
        
        vector = model.encode(text_to_embed).tolist()
        
        points.append(models.PointStruct(
            id=i,
            vector=vector,
            payload={
                "url": url,
                "date": date,
                "description": description
            }
        ))

    # 5. Upsert into Qdrant in one batch
    print(f"Upserting {len(points)} points into Qdrant...")
    client.upsert(
        collection_name=collection_name,
        points=points
    )

    print("Ingestion complete.")

if __name__ == "__main__":
    ingest_to_qdrant()
