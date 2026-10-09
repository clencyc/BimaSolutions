const printButtons = [
  document.querySelector("#generateReport"),
  document.querySelector("#printReport"),
];

printButtons.forEach((button) => {
  button.addEventListener("click", () => window.print());
});

const navLinks = document.querySelectorAll(".nav-link");

navLinks.forEach((link) => {
  link.addEventListener("click", () => {
    navLinks.forEach((navLink) => {
      navLink.classList.remove("active");
      navLink.removeAttribute("aria-current");
    });
    link.classList.add("active");
    link.setAttribute("aria-current", "page");
  });
});
