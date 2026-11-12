// 聚合管道：按品类、按月、关联、分面
use shop

// ---- 1. 按一级品类统计销售额（某月） ----
db.orders.aggregate([
  { $match: { status: { $in: ["paid", "shipped", "completed"] },
              created_at: { $gte: ISODate("2026-10-01T00:00:00Z"),
                            $lt:  ISODate("2026-11-01T00:00:00Z") } } },
  { $unwind: "$items" },
  { $lookup: { from: "products", localField: "items.product_id",
               foreignField: "_id", as: "p" } },
  { $unwind: "$p" },
  { $group: { _id: { $arrayElemAt: ["$p.category_path", 0] },
              revenue: { $sum: { $multiply: ["$items.price", "$items.qty"] } },
              orderIds: { $addToSet: "$_id" } } },
  { $project: { _id: 0, category: "$_id", revenue: 1,
                orderCount: { $size: "$orderIds" } } },
  { $sort: { revenue: -1 } },
  { $limit: 10 }
]);

// ---- 2. 按月统计订单量与客单价 ----
db.orders.aggregate([
  { $match: { status: { $in: ["paid", "shipped", "completed"] } } },
  { $group: { _id: { $dateToString: { format: "%Y-%m", date: "$created_at",
                                      timezone: "Asia/Shanghai" } },
              orders: { $sum: 1 },
              revenue: { $sum: "$amount.payable" },
              avgTicket: { $avg: "$amount.payable" } } },
  { $sort: { _id: 1 } },
  { $limit: 4 }
]);

// ---- 3. 关联统计：金牌用户的有效订单数与评论数 ----
db.users.aggregate([
  { $match: { level: "gold" } },
  { $lookup: {
      from: "orders",
      let: { uid: "$_id" },
      pipeline: [
        { $match: { $expr: { $and: [{ $eq: ["$user_id", "$$uid"] },
                                    { $eq: ["$status", "paid"] }] } } },
        { $count: "n" } ],
      as: "paidOrders" } },
  { $lookup: { from: "reviews", localField: "_id", foreignField: "user_id", as: "rv" } },
  { $project: { nickname: 1, level: 1,
                paidOrderCount: { $ifNull: [{ $arrayElemAt: ["$paidOrders.n", 0] }, 0] },
                reviewCount: { $size: "$rv" }, _id: 0 } },
  { $sort: { paidOrderCount: -1 } },
  { $limit: 3 }
]);

// ---- 4. $facet 多维分面 + $bucket 价格分桶 ----
db.products.aggregate([
  { $match: { status: "on_sale" } },
  { $facet: {
      byCategory: [
        { $group: { _id: { $arrayElemAt: ["$category_path", 0] },
                    n: { $sum: 1 }, avgPrice: { $avg: "$price.sale" } } },
        { $sort: { n: -1 } } ],
      priceBuckets: [
        { $bucket: { groupBy: "$price.sale",
                     boundaries: [NumberDecimal("0"),  NumberDecimal("20"),
                                  NumberDecimal("50"), NumberDecimal("100"),
                                  NumberDecimal("200"), NumberDecimal("500")],
                     default: "500+",
                     output: { n: { $sum: 1 }, avgRating: { $avg: "$rating.score" } } } } ],
      topRated: [
        { $sort: { "rating.score": -1 } },
        { $limit: 3 },
        { $project: { _id: 0, title: 1, "rating.score": 1 } } ] } }
]);
