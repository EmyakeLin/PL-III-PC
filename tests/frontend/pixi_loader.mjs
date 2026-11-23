export async function resolve(specifier, context, next) {
  if (specifier.endsWith('pixi.min.mjs')) {
    return { url: new URL('./pixi_stub.mjs', import.meta.url).href, shortCircuit: true };
  }
  return next(specifier, context);
}
