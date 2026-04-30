use thiserror::Error;

#[derive(Error, Debug)]
pub enum FinError {
    #[error("{0}")]
    Invalid(String),
    #[error(transparent)]
    Db(#[from] rusqlite::Error),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error("{0}")]
    Other(String),
}

impl From<anyhow::Error> for FinError {
    fn from(e: anyhow::Error) -> Self {
        FinError::Other(e.to_string())
    }
}

pub type Result<T> = std::result::Result<T, FinError>;

impl FinError {
    pub fn invalid(msg: impl Into<String>) -> Self {
        FinError::Invalid(msg.into())
    }
}
