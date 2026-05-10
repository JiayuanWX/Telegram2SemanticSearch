import sys
import argparse
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

def main():
    parser = argparse.ArgumentParser(description="Semantic search for Telegram URLs in Qdrant")
    parser.add_argument("query", help="The search query")
    parser.add_argument("--top", "-k", type=int, default=3, help="Number of results to return (default: 3)")
    args = parser.parse_args()

    client = QdrantClient("localhost", port=6333)
    collection_name = "tg_urls"

    if not client.collection_exists(collection_name):
        print(f"Error: Collection '{collection_name}' not found. Run ingest_qdrant.py first.")
        return

    # Load BGE model
    model = SentenceTransformer('BAAI/bge-small-en-v1.5')
    
    # Embed the query
    query_vector = model.encode(args.query).tolist()

    # Search
    results = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        limit=args.top
    ).points

    # Get total count for the footer
    total_count = client.get_collection(collection_name).points_count

    print(f"\n🔍 Searching: \"{args.query}\"")
    print("─" * 70)

    for i, res in enumerate(results):
        payload = res.payload
        score = res.score
        print(f"#{i+1} score: {score:.3f}")
        print(f" date: {payload.get('date')}")
        print(f" url: {payload.get('url')}")
        print(f" desc: {payload.get('description')}")
        print("─" * 70)

    print(f"Showing {len(results)} of {total_count} entries.\n")

if __name__ == "__main__":
    main()
