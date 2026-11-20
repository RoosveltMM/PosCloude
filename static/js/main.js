// Auto-ocultar flash messages después de 4 segundos
document.addEventListener("DOMContentLoaded", () => {
    const flashes = document.querySelectorAll(".flash");
    flashes.forEach(f => {
        setTimeout(() => {
            f.style.transition = "opacity .4s";
            f.style.opacity = "0";
            setTimeout(() => f.remove(), 400);
        }, 4000);
    });
});
