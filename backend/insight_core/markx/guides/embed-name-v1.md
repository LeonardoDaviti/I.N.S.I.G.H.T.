# Name embedding guide (Mark X 0119 A1, embed name v1)

No model reads this guide: an `embed_name` task is answered by the embedder, as an `embed` task is (embed-v1), not by Haiku.

- **The model:** BGE-M3, the same GGUF and build as the posts' vectors (`llama-server --embedding --pooling cls`); its sha256 is sent with every vector, and the server keeps one build per database.
- **The text:** the task's input exactly as given: one entity's shown name ("Acme Nimbus 5.5"). No instruction prefix.
- **The vector:** the CLS vector of 1,024 dimensions, scaled to length 1, as 1,024 little-endian float16 (2,048 bytes), base64.
- **Where it goes:** `POST /api/markx/embeddings`, as an `embed` task's vector. The server stores it for the entity, and the alias candidates read a name's 10 nearest names at a cosine of 0.80 or more.
