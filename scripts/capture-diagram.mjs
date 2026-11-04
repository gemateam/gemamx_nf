/**
 * capture-diagram.mjs
 * Abre architecture.html con Chrome headless y exporta un PNG de alta resolución.
 * Espera a que el SVG de Archify esté completamente renderizado antes de capturar.
 */
import puppeteer from 'puppeteer';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const htmlPath = path.resolve(__dirname, '../docs/architecture.html');
const outPath  = path.resolve(__dirname, '../docs/architecture.png');

// Usa el Chrome administrado por Puppeteer. Si se necesita un binario
// concreto, se puede indicar con CHROME_PATH sin editar el script.
const browser = await puppeteer.launch({
  headless: true,
  ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
  args: ['--no-sandbox', '--disable-setuid-sandbox'],
});

const page = await browser.newPage();

// Viewport amplio para el diagrama completo
await page.setViewport({ width: 1400, height: 900, deviceScaleFactor: 2 });

// Cargar el archivo local
await page.goto(`file:///${htmlPath.replace(/\\/g, '/')}`, { waitUntil: 'networkidle0', timeout: 30000 });

// Esperar a que el SVG principal de Archify esté en el DOM
await page.waitForSelector('svg', { timeout: 20000 });

// Dar tiempo extra para animaciones de entrada
await new Promise(r => setTimeout(r, 3000));

// Obtener el bounding box real del SVG para capturar exactamente el diagrama
const svgSize = await page.evaluate(() => {
  const svg = document.querySelector('svg');
  if (!svg) return null;
  const rect = svg.getBoundingClientRect();
  return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
});

console.log('SVG size:', svgSize);

// Capturar fullpage o el SVG exacto
await page.screenshot({
  path: outPath,
  fullPage: false,
  clip: svgSize
    ? { x: 0, y: 0, width: Math.min(svgSize.width + 40, 1400), height: Math.min(svgSize.height + 40, 900) }
    : undefined,
});

console.log(`PNG guardado en: ${outPath}`);
await browser.close();
