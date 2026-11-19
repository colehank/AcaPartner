/** Project an Outliner occurrence onto the identity-only editor-area protocol.
 * Tree presentation/provenance fields must never become executable commands.
 */
export function selectionForRegion(node, open = false) {
  const source = node?.anchor || {};
  const anchor = {type: source.type};
  for (const name of ['id','artistId','blockId','componentId','itemId','parentObjectId']) {
    if (typeof source[name] === 'string' && source[name]) anchor[name] = source[name];
  }
  for (const name of ['componentIndex','revision','pageIndex']) {
    if (Number.isSafeInteger(source[name]) && source[name] >= 0) anchor[name] = source[name];
  }
  return {objectId: source.type === 'component' ? source.parentObjectId : node?.objectId, anchor, open};
}
