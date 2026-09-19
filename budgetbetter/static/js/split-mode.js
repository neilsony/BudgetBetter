// The new-expense form: which controls apply depends on how the Expense splits.
(function () {
  const mode = document.getElementById("split_mode");
  const picker = document.getElementById("picker");
  const modehint = document.getElementById("modehint");
  const pickerhint = document.getElementById("pickerhint");
  const amount = document.getElementById("amount");
  if (!mode || !picker || !amount) return;

  const customs = [...document.querySelectorAll(".customamt")];

  const HINTS = {
    equal_all: "Every active member, you included.",
    equal_selected: "Split evenly between whoever you tick. You are always included.",
    custom: "Type what each person owes. They must add up to the total, and yours may be zero.",
    reimbursement: "The people you tick owe the whole amount. You take no share.",
  };

  function sync() {
    const m = mode.value;
    picker.hidden = m === "equal_all";
    modehint.textContent = HINTS[m];
    customs.forEach((input) => {
      input.hidden = m !== "custom";
    });
    // A custom split's total is whatever the per-person amounts add up to.
    amount.disabled = m === "custom";
    pickerhint.textContent = m === "custom" ? "The total is whatever these add up to." : "";
  }

  mode.addEventListener("change", sync);
  sync();
})();
