from typing import List
from openai import OpenAI

from core.embeddings.base import BaseEmbedding

class OpenAIEmbedding(BaseEmbedding):
    def __init__(self, model: str = "text-embedding-3-small",api_key: str = None, base_url: str = None):
        self.model = model
        self.client = OpenAI(api_key=api_key,base_url=base_url)
    def embed(self,texts:List[str]) -> List[List[float]]:
        resp = self.client.embeddings.create(model = self.model, input = texts)
        return [item.embedding for item in resp.data]
    def embed_query(self, text: str) -> List[float]:
        return self.embed([text])[0]