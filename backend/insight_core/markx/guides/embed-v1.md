# Embedding guide (Mark X F0.4, embed v1)

No model reads this guide: an `embed` task is answered by an embedder, not by Haiku. It says how, so a vector from any device is the same vector.

- **The model:** BGE-M3, the GGUF `bge-m3-q8_0.gguf`, served by llama.cpp's `llama-server --embedding --pooling cls` on the device. Its sha256 is sent with every vector; the server keeps one build per database.
- **The text:** the task's input, exactly as given (markx embed text v1: the title unless the text starts with it, then the first 1,500 characters of the text, web addresses removed, spaces squashed). No instruction prefix.
- **The vector:** the CLS vector of 1,024 dimensions, scaled to length 1, as 1,024 little-endian float16 (2,048 bytes), base64.
- **Where it goes:** `POST /api/markx/embeddings`, never `/api/markx/answers`.
