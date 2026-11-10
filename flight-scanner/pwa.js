if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  });
}
let installPrompt;
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  installPrompt = event;
  document.getElementById("install").hidden = false;
});
document.getElementById("install").addEventListener("click", async () => {
  if (!installPrompt) return;
  await installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  document.getElementById("install").hidden = true;
});
window.addEventListener("appinstalled", () => {
  installPrompt = null;
  document.getElementById("install").hidden = true;
});
