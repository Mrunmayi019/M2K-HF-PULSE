export function Skeleton({ width = '100%', height = 16, style = {} }) {
  return <div className="skeleton" style={{ width, height, ...style }} />
}

export function DashboardSkeleton() {
  return (
    <>
      <div className="section">
        <div className="card hero">
          <Skeleton width={140} height={28} style={{ marginBottom: 12 }} />
          <Skeleton width={260} height={22} style={{ marginBottom: 8 }} />
          <Skeleton width={380} height={16} />
        </div>
      </div>
      <div className="section">
        <div className="grid2">
          <div className="card condleft">
            <Skeleton width={200} height={20} style={{ marginBottom: 16 }} />
            <Skeleton width="100%" height={64} />
          </div>
          <div className="card metriccol">
            <Skeleton height={64} />
            <Skeleton height={64} />
            <Skeleton height={64} />
          </div>
        </div>
      </div>
      <div className="section">
        <div className="card" style={{ padding: 24 }}>
          <Skeleton height={200} />
        </div>
      </div>
    </>
  )
}
