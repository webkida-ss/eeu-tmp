use std::{
    collections::HashMap,
    sync::{Mutex, MutexGuard},
};

use async_trait::async_trait;
use uuid::Uuid;

use crate::{
    application::ports::{UserRepository, UserRepositoryError},
    domain::user::{User, UserIdentity},
};

#[derive(Debug, Default)]
pub struct InMemoryUserRepository {
    state: Mutex<InMemoryUserState>,
}

#[derive(Debug, Default)]
struct InMemoryUserState {
    users: HashMap<Uuid, User>,
    identities: HashMap<(String, String), UserIdentity>,
}

impl InMemoryUserRepository {
    pub fn new() -> Self {
        Self::default()
    }

    fn lock_state(&self) -> Result<MutexGuard<'_, InMemoryUserState>, UserRepositoryError> {
        self.state
            .lock()
            .map_err(|_| UserRepositoryError::Unavailable)
    }
}

#[async_trait]
impl UserRepository for InMemoryUserRepository {
    async fn find_user_by_identity(
        &self,
        provider: &str,
        subject: &str,
    ) -> Result<Option<User>, UserRepositoryError> {
        let state = self.lock_state()?;
        let key = (provider.to_string(), subject.to_string());

        Ok(state
            .identities
            .get(&key)
            .and_then(|identity| state.users.get(&identity.user_id))
            .cloned())
    }

    async fn create_user_for_identity(
        &self,
        provider: &str,
        subject: &str,
        email: &str,
    ) -> Result<User, UserRepositoryError> {
        let mut state = self.lock_state()?;
        let key = (provider.to_string(), subject.to_string());

        if let Some(existing_user) = state
            .identities
            .get(&key)
            .and_then(|identity| state.users.get(&identity.user_id))
            .cloned()
        {
            return Ok(existing_user);
        }

        let user = User {
            id: Uuid::now_v7(),
            email: email.to_string(),
        };
        let identity = UserIdentity {
            user_id: user.id,
            provider: provider.to_string(),
            subject: subject.to_string(),
        };

        state.users.insert(user.id, user.clone());
        state.identities.insert(key, identity);

        Ok(user)
    }
}
