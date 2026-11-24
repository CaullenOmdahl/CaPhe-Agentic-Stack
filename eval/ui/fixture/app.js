const ITEMS = ["Apple", "Banana", "Apricot", "Cherry", "Tom & <Jerry>", "grape"];

const list = document.getElementById("list");

function render(items) {
  list.textContent = "";
  for (const name of items) {
    const li = document.createElement("li");
    li.textContent = name;
    list.appendChild(li);
  }
}

render(ITEMS);
