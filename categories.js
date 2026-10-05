/* ==========================================================================
   VoltCraft Categories Showcase JavaScript (categories.js)
   Handles dynamic search and pill-based filtering
   ========================================================================== */

document.addEventListener('DOMContentLoaded', function () {
    const searchInput = document.getElementById('categorySearchInput');
    const filterPills = document.querySelectorAll('.cat-pill-btn');
    const categoryCols = document.querySelectorAll('.category-item-col');
    const noMatchMessage = document.getElementById('noMatchMessage');

    function filterCategories() {
        const query = (searchInput.value || '').trim().toLowerCase();
        const activePill = document.querySelector('.cat-pill-btn.active');
        const filterType = activePill ? activePill.getAttribute('data-filter') : 'all';

        let visibleCount = 0;

        categoryCols.forEach(col => {
            const name = col.getAttribute('data-name') || '';
            const desc = col.getAttribute('data-desc') || '';

            let matchesSearch = !query || name.includes(query) || desc.includes(query);
            let matchesFilter = true;

            if (filterType === 'ac') {
                matchesFilter = name.includes('ac') || name.includes('condition') || name.includes('air');
            } else if (filterType === 'fridge') {
                matchesFilter = name.includes('fridge') || name.includes('refrigerat') || name.includes('freezer');
            } else if (filterType === 'wash') {
                matchesFilter = name.includes('wash') || name.includes('dryer') || name.includes('laundry');
            } else if (filterType === 'kitchen') {
                matchesFilter = name.includes('microwave') || name.includes('oven') || name.includes('dish') || name.includes('chimney') || name.includes('cook') || name.includes('mixer') || name.includes('grind');
            } else if (filterType === 'water') {
                matchesFilter = name.includes('purif') || name.includes('water') || name.includes('ro') || name.includes('geyser') || name.includes('heater');
            } else if (filterType === 'living') {
                matchesFilter = name.includes('tv') || name.includes('televis') || name.includes('cooler') || name.includes('fan') || name.includes('vacuum') || name.includes('clean');
            }

            if (matchesSearch && matchesFilter) {
                col.classList.remove('d-none');
                visibleCount++;
            } else {
                col.classList.add('d-none');
            }
        });

        if (visibleCount === 0) {
            noMatchMessage.classList.remove('d-none');
        } else {
            noMatchMessage.classList.add('d-none');
        }
    }

    // Live search listener
    if (searchInput) {
        searchInput.addEventListener('input', filterCategories);
    }

    // Filter pill buttons
    filterPills.forEach(pill => {
        pill.addEventListener('click', function () {
            filterPills.forEach(p => p.classList.remove('active'));
            this.classList.add('active');
            filterCategories();
        });
    });

    window.resetCategorySearch = function() {
        if (searchInput) searchInput.value = '';
        filterPills.forEach(p => p.classList.remove('active'));
        if (filterPills[0]) filterPills[0].classList.add('active');
        filterCategories();
    };
});
