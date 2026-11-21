// Chrome and Node's fetch can leave open HTTP connections after a download.
// Stop accepting connections first, then release active ones as well.
export async function closePreview(server) {
  await new Promise((resolve, reject) => {
    server.httpServer.close(error => error ? reject(error) : resolve());
    server.httpServer.closeAllConnections();
  });
}
