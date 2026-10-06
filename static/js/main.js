// Funciones generales para el sistema
document.addEventListener('DOMContentLoaded', function() {
    // Inicializar tooltips de bootstrap
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl)
    })

    console.log('Sistema Gestor de Silos cargado correctamente.');
});
