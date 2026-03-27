export function toData(requestPromise) {
  return requestPromise.then((response) => response.data)
}
