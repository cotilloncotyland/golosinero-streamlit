const FOLDER_ID = '1VewexnNy_jfZZ8lu_HMdExaYvFyK75yZ';
const IMAGES_INDEX_FILE_ID = '1fqSlwCqGvyB2W9W0b-3zZrvxp-KjHI4i';
const IMAGE_FOLDER_NAMES = ['imagenes_productos_optimizadas', 'imagenes_productos'];
const IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp'];

function regenerarIndiceImagenes() {
  const root = DriveApp.getFolderById(FOLDER_ID);
  const stats = { encontradas: 0, indexadas: 0, omitidas: 0, duplicados: 0 };
  const out = {
    generatedAt: new Date().toISOString(),
    logoUrl: obtenerLogoUrl_(root),
    images: {}
  };

  IMAGE_FOLDER_NAMES.forEach(function(folderName) {
    const folder = buscarCarpeta_(root, folderName);
    if (!folder) {
      console.log('Carpeta no encontrada: ' + folderName);
      return;
    }
    indexarCarpetaRecursiva_(folder, folderName, out.images, stats);
  });

  const jsonFile = obtenerArchivoIndice_(root);
  jsonFile.setContent(JSON.stringify(out, null, 2));
  console.log('imagenes_index.json actualizado: ' + jsonFile.getId());
  console.log('Imágenes encontradas: ' + stats.encontradas);
  console.log('Imágenes indexadas: ' + stats.indexadas);
  console.log('Imágenes omitidas: ' + stats.omitidas);
  console.log('Duplicados: ' + stats.duplicados);
  return { archivoId: jsonFile.getId(), estadisticas: stats, indice: out };
}

function verificarImagenSku(sku) {
  const normalizedSku = normalizarSkuImagen_(sku);
  const root = DriveApp.getFolderById(FOLDER_ID);
  const matches = [];

  IMAGE_FOLDER_NAMES.forEach(function(folderName) {
    const folder = buscarCarpeta_(root, folderName);
    if (folder) buscarSkuRecursivo_(folder, folderName, normalizedSku, matches);
  });

  const indexFile = obtenerArchivoIndice_(root);
  const indexData = JSON.parse(indexFile.getBlob().getDataAsString('UTF-8'));
  const result = {
    sku: normalizedSku,
    encontrada: matches.length > 0,
    carpeta: matches.length ? matches[0].carpeta : '',
    nombre: matches.length ? matches[0].nombre : '',
    id: matches.length ? matches[0].id : '',
    url: matches.length ? matches[0].url : '',
    incluidaEnIndice: !!(indexData.images && indexData.images[normalizedSku]),
    urlEnIndice: indexData.images && indexData.images[normalizedSku] || '',
    coincidencias: matches
  };
  console.log(JSON.stringify(result, null, 2));
  return result;
}

function indexarCarpetaRecursiva_(folder, path, images, stats) {
  const files = folder.getFiles();
  while (files.hasNext()) {
    const file = files.next();
    stats.encontradas++;
    const info = datosImagen_(file, path);
    if (!info) {
      stats.omitidas++;
      console.log('Omitida: ' + path + '/' + file.getName());
      continue;
    }
    if (images[info.sku]) {
      stats.duplicados++;
      console.log('Duplicada: ' + info.sku + ' en ' + path + '/' + info.nombre);
      continue;
    }
    file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
    images[info.sku] = info.url;
    stats.indexadas++;
    console.log('Indexada: ' + info.sku + ' en ' + path + '/' + info.nombre);
  }

  const folders = folder.getFolders();
  while (folders.hasNext()) {
    const child = folders.next();
    indexarCarpetaRecursiva_(child, path + '/' + child.getName(), images, stats);
  }
}

function buscarSkuRecursivo_(folder, path, sku, matches) {
  const files = folder.getFiles();
  while (files.hasNext()) {
    const file = files.next();
    const info = datosImagen_(file, path);
    if (info && info.sku === sku) matches.push(info);
  }
  const folders = folder.getFolders();
  while (folders.hasNext()) {
    const child = folders.next();
    buscarSkuRecursivo_(child, path + '/' + child.getName(), sku, matches);
  }
}

function datosImagen_(file, path) {
  const name = String(file.getName() || '').trim();
  const dot = name.lastIndexOf('.');
  if (dot < 1) return null;
  const extension = name.slice(dot + 1).toLowerCase();
  if (IMAGE_EXTENSIONS.indexOf(extension) === -1) return null;
  const sku = normalizarSkuImagen_(name.slice(0, dot));
  if (!sku) return null;
  return {
    sku: sku,
    carpeta: path,
    nombre: name,
    id: file.getId(),
    url: driveThumbUrl_(file.getId(), 220)
  };
}

function normalizarSkuImagen_(value) {
  return String(value || '')
    .normalize('NFKC')
    .replace(/^\uFEFF/, '')
    .trim()
    .replace(/\s+/g, '')
    .toLowerCase();
}

function obtenerArchivoIndice_(root) {
  const file = DriveApp.getFileById(IMAGES_INDEX_FILE_ID);
  if (file.getName() !== 'imagenes_index.json') {
    throw new Error('El ID configurado no corresponde a imagenes_index.json');
  }
  return file;
}

function obtenerLogoUrl_(root) {
  const logoFolder = buscarCarpeta_(root, 'logo');
  if (!logoFolder) return '';
  const files = logoFolder.getFiles();
  while (files.hasNext()) {
    const file = files.next();
    if (datosImagen_(file, 'logo')) {
      file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
      return driveThumbUrl_(file.getId(), 500);
    }
  }
  return '';
}

function buscarCarpeta_(folder, name) {
  const folders = folder.getFoldersByName(name);
  return folders.hasNext() ? folders.next() : null;
}

function driveThumbUrl_(fileId, size) {
  return 'https://drive.google.com/thumbnail?id=' + fileId + '&sz=w' + size;
}
