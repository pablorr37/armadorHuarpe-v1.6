// Seleccioná primero la(s) caja(s) con la herramienta Item Tool
var boxes = app.activeBoxesDOM();
if (!boxes || boxes.length === 0) {
    app.dialogs.alert('Seleccioná al menos una caja.');
} else {
    var nombreActual = boxes[0].getAttribute('box-name') || '';
    var nombre = app.dialogs.prompt('Nombre para la caja:', nombreActual);
    if (nombre !== null && nombre.trim() !== '') {
        nombre = nombre.trim();
        app.undo.beginCompoundUndo('Renombrar caja');
        try {
            for (var i = 0; i < boxes.length; i++) {
                boxes[i].setAttribute('box-name', nombre);
            }
        } finally {
            app.undo.endCompoundUndo();
        }
    }
}
