// Two-step Refresh: the first click only reveals the confirmation.
// Deliberate friction — see ADR-0007. Shared by the budgeting and investing
// pages, which previously carried a byte-for-byte copy of this each.
(function () {
  const btn = document.getElementById("refreshBtn");
  const box = document.getElementById("confirmBox");
  const cancel = document.getElementById("cancelBtn");
  const form = document.getElementById("refreshForm");
  if (!btn || !box || !cancel || !form) return;

  btn.addEventListener("click", () => {
    btn.hidden = true;
    box.hidden = false;
  });

  cancel.addEventListener("click", () => {
    box.hidden = true;
    btn.hidden = false;
  });

  form.addEventListener("submit", (e) => {
    e.submitter.disabled = true;
    e.submitter.textContent = "Refreshing…";
  });
})();
