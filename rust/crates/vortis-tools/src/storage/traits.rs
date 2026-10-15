//! MemoryBackend trait for all storage backends.

use vortis_core::{VortisError, RetrievalResult};
use serde_json::Value;

pub trait MemoryBackend: Send + Sync {
    fn backend_id(&self) -> &str;
    fn store(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
    ) -> Result<String, VortisError>;
    fn retrieve(
        &self,
        query: &str,
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, VortisError>;
    fn delete(&self, doc_id: &str) -> Result<bool, VortisError>;
    fn clear(&self) -> Result<(), VortisError>;
    fn count(&self) -> Result<usize, VortisError>;
}
