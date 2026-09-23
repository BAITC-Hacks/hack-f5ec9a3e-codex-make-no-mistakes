import React from 'react';
import { createRoot } from 'react-dom/client';
// Keep the approved purchasing layout as the application entry point.
import ElektroWorkspace from './elektro-workspace.jsx';

createRoot(document.getElementById('root')).render(<ElektroWorkspace/>);
