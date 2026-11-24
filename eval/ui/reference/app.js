const ITEMS = ["Apple", "Banana", "Apricot", "Cherry", "Tom & <Jerry>", "grape"];

const list = document.getElementById("list");
const q = document.getElementById("q");
const count = document.getElementById("count");
const empty = document.getElementById("empty");

function render(items) {
  list.textContent = "";
  for (const name of items) {
    const li = document.createElement("li");
    li.textContent = name;
    list.appendChild(li);
  }
  count.textContent = `${items.length} of ${ITEMS.length} shown`;
  empty.hidden = items.length > 0;
}

q.addEventListener("input", () => {
  const needle = q.value.trim().toLowerCase();
  render(ITEMS.filter((name) => name.toLowerCase().includes(needle)));
});

render(ITEMS);
