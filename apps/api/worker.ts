export default {
  fetch() {
    return new Response('Temporarily unavailable\n', {
      status: 500,
      headers: {
        'Content-Type': 'text/plain; charset=utf-8',
        'Cache-Control': 'no-store',
      },
    })
  },
}
