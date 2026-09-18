use std::net::SocketAddr;

#[tokio::main]
async fn main() -> Result<(), english_backend::bootstrap::BootstrapError> {
    let app = english_backend::bootstrap::build_app().await?;
    let listener = tokio::net::TcpListener::bind(app.config.listen_addr()).await?;
    let local_addr: SocketAddr = listener.local_addr()?;

    tracing::info!(%local_addr, "backend server listening");

    axum::serve(listener, app.router)
        .with_graceful_shutdown(shutdown_signal())
        .await?;

    Ok(())
}

async fn shutdown_signal() {
    let ctrl_c = async {
        tokio::signal::ctrl_c()
            .await
            .expect("failed to install Ctrl+C handler");
    };

    #[cfg(unix)]
    let terminate = async {
        tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("failed to install terminate signal handler")
            .recv()
            .await;
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }
}
