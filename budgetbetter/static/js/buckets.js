// Setting a Bucket by hand writes an Override, which beats every Rule and
// survives later refreshes. See ADR-0003.
(function () {
  document.querySelectorAll("select.bucket").forEach((select) => {
    select.addEventListener("change", async () => {
      const body = new FormData();
      body.append("bucket", select.value);
      select.disabled = true;
      await fetch(`/transactions/${select.dataset.txn}/bucket`, {
        method: "POST",
        body,
      });
      select.disabled = false;
    });
  });
})();
