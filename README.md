# Vis2026 - Similarity Graph Explorer

A web application designed to transform `.ris` files into article similarity graphs, detect communities, and visually explore the results.

## MVP Features

- **`.ris` File Upload:** Easy ingestion of academic metadata.
- **Metadata Extraction:** Extracts titles, abstracts, and keywords.
- **Text Embedding:** Powered by `all-MiniLM-L6-v2`.
- **Graph Construction:** Supports both `epsilon-threshold` and `K-NN` methods.
- **Community Detection:** Implements the Louvain algorithm.
- **Interactive Graph:** Features search, node selection, and a detailed metadata panel.
- **Global Network Statistics:** Provides insights into the generated graph network.
- **Data Export:** Export articles, edges, and community data.

## How to Run

### 1. Clone the repository
```bash
git clone [https://github.com/YOUR_USERNAME/Vis2026.git](https://github.com/YOUR_USERNAME/Vis2026.git)
cd Vis2026
```

### 2. Setup the virtual environment
On Windows (PowerShell):
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

On macOS / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the server
```bash
uvicorn server:app --reload
```
Once started, access the application at: http://localhost:8000

## Notes

- **First Run:** The first time you run the application, it might take a while to start as sentence-transformers needs to download and cache the embedding model locally.

- **Graph Updates:** Changing epsilon, k, or the method after uploading a file will not automatically recalculate the graph. The graph is updated only after clicking APPLY.