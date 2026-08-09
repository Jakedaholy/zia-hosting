// TyraDev front-end helpers
document.addEventListener("DOMContentLoaded", () => {
  // auto-hide flashes
  setTimeout(() => {
    document.querySelectorAll(".flash").forEach((el) => {
      el.style.opacity = "0";
      el.style.transition = "opacity .4s";
      setTimeout(() => el.remove(), 400);
    });
  }, 4000);
});

