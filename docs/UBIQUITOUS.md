# Ubiquitous Language

## Terms

### Personalized example sentence

An example sentence adapted to an individual learner's context, such as interests, work situation, goals, weak vocabulary, or saved focus words. It is stored as learning content and shown without requiring the learner to manually request generation. AI can be used behind the scenes, but personalization is the domain concept.

### User context

The learner-specific information used to personalize recommendations and example sentences. This can include profile data, learning goals, interests, saved words, weak words, and writing history.

### AI model catalog

The application-owned list of AI models that feature clients are allowed to request. It maps approved model choices to provider-specific model identifiers and prevents feature code or UI users from depending directly on vendor model names. In production, this catalog is application data stored in the database so model routing can change without redeploying application code. It does not contain provider API keys or secrets.

### Personalization job

An asynchronous application command that regenerates stored personalized example sentences after learner context changes. The job carries only the learner id, profile version, idempotency key, and reason; workers reload the current learning context from storage.

### Stored personalized example sentence

A personalized example sentence persisted as normal learning content for a learner. Study screens read this content through backend APIs and do not depend on live AI generation.
