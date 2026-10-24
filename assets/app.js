document.querySelectorAll('[data-confirm]').forEach(form=>form.addEventListener('submit',event=>{if(!confirm(form.dataset.confirm))event.preventDefault();}));
document.querySelectorAll('[data-print]').forEach(button=>button.addEventListener('click',()=>window.print()));
const seatLabels={active:'مقعد نشط',aisle:'ممر',disabled:'معطّل'};
document.querySelectorAll('[data-seat-cycle]').forEach(button=>button.addEventListener('click',()=>{const seat=button.closest('.seat');const input=seat.querySelector('input[data-seat-state]');const values=['active','aisle','disabled'];const value=values[(values.indexOf(input.value)+1)%values.length];input.value=value;seat.classList.remove(...values);seat.classList.add(value);button.textContent=seatLabels[value];}));
