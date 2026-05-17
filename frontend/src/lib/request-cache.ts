type CacheEntry<T> = {
  value?: T
  expiresAt: number
  promise?: Promise<T>
}

class RequestCache {
  private entries = new Map<string, CacheEntry<unknown>>()

  get<T>(key: string, loader: () => Promise<T>, ttlMs: number): Promise<T> {
    const now = Date.now()
    const current = this.entries.get(key) as CacheEntry<T> | undefined
    if (current?.value !== undefined && current.expiresAt > now) {
      return Promise.resolve(current.value)
    }
    if (current?.promise) {
      return current.promise
    }

    const promise = loader()
      .then((value) => {
        this.entries.set(key, {
          value,
          expiresAt: Date.now() + ttlMs,
        })
        return value
      })
      .catch((error) => {
        if (current?.value !== undefined) {
          this.entries.set(key, current)
        } else {
          this.entries.delete(key)
        }
        throw error
      })

    this.entries.set(key, {
      value: current?.value,
      expiresAt: current?.expiresAt ?? 0,
      promise,
    })
    return promise
  }

  invalidate(prefix: string) {
    for (const key of this.entries.keys()) {
      if (key.startsWith(prefix)) {
        this.entries.delete(key)
      }
    }
  }

  clear() {
    this.entries.clear()
  }
}

export const requestCache = new RequestCache()
