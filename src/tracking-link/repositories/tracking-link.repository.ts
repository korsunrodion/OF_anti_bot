import { Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { EntityManager, In, MoreThanOrEqual, Repository } from 'typeorm';
import { UpsertTrackingLinkDto } from '../dto/upsert-tracking-link.dto';
import { TrackingLinkInput } from '../entities/tracking-link-input.entity';
import {
  RiskLevel,
  TrackingLinkSubscriber,
} from '../entities/tracking-link-subscriber.entity';
import { TrackingLinkSubscriptionDto } from '../dto/tracking-link-subscription.dto';
import { TrackingLinkDto } from '../dto/tracking-link.dto';
import { SubscriberDto } from '../dto/subscriber.dto';

export interface SubscriberFilter {
  createdSince?: string;
  updatedSince?: string;
  riskLevel?: RiskLevel[];
}

@Injectable()
export class TrackingLinkRepository {
  constructor(
    @InjectRepository(TrackingLinkInput)
    private readonly inputRepo: Repository<TrackingLinkInput>,
    @InjectRepository(TrackingLinkSubscriber)
    private readonly subscriberRepo: Repository<TrackingLinkSubscriber>,
  ) {}

  async upsert(dto: UpsertTrackingLinkDto): Promise<void> {
    await this.inputRepo.save({
      id: String(dto.trackingLinkId),
      trackingLinkId: dto.trackingLinkId,
      trackingLinkName: dto.trackingLinkName,
      isProcessed: false,
      subscribers: dto.subscriptions,
    });
  }

  async findUnprocessed(): Promise<TrackingLinkInput[]> {
    return this.inputRepo.findBy({ isProcessed: false });
  }

  async upsertSubscribers(
    manager: EntityManager,
    trackingLinkId: number,
    trackingLinkName: string,
    newSubscribers: SubscriberDto[],
  ): Promise<void> {
    const ids = newSubscribers.map((s) => `${trackingLinkId}_${s.id}`);
    // Look up which row-ids already exist so we DON'T overwrite their
    // original createdAt on update — only newly inserted rows get a fresh
    // createdAt. (manager.save chooses INSERT vs UPDATE per row based on
    // whether the primary key exists.)
    const existingIds = new Set(
      (
        await manager.find(TrackingLinkSubscriber, {
          where: { id: In(ids) },
          select: ['id'],
        })
      ).map((e) => e.id),
    );
    // Stamp every newly inserted row this batch with the same `createdAt`
    // so the value reflects when this upsert wrote them, independent of
    // whether @CreateDateColumn fires.
    const now = new Date();
    const entities = newSubscribers.map((s) => {
      const id = `${trackingLinkId}_${s.id}`;
      return manager.create(TrackingLinkSubscriber, {
        id,
        trackingLinkId,
        trackingLinkName,
        username: s.username,
        userId: s.userId,
        subscriptionDate: s.subscriptionDate,
        avatarUrl: s.avatarUrl,
        header: s.header,
        isOnlineMatchesSubscription: s.isOnlineMatchesSubscription,
        isReadingMessages: s.isReadingMessages,
        // Only set createdAt for genuinely new rows; omit on existing rows
        // so manager.save's UPDATE leaves the original timestamp alone.
        ...(existingIds.has(id) ? {} : { createdAt: now }),
      });
    });
    await manager.save(TrackingLinkSubscriber, entities);
  }

  async markProcessed(manager: EntityManager, id: string): Promise<void> {
    await manager.update(TrackingLinkInput, id, { isProcessed: true });
  }

  async findAllSubscriptions(
    page: number,
    limit: number,
    filter: SubscriberFilter = {},
  ): Promise<[TrackingLinkSubscriptionDto[], number]> {
    const [rows, total] = await this.subscriberRepo.findAndCount({
      where: {
        isInternalData2: false,
        ...buildTimestampFilter(filter),
      },
      // Stable ordering on the immutable primary key so paginated callers
      // don't see duplicates / misses when other writes (e.g. the predict
      // job's bulk UPDATE) rewrite the heap between page fetches.
      order: { id: 'ASC' },
      skip: (page - 1) * limit,
      take: limit,
    });
    return [rows.map(toSubscriptionDto), total];
  }

  async findSubscriptionsByLinkId(
    trackingLinkId: number,
    filter: SubscriberFilter = {},
  ): Promise<TrackingLinkSubscriptionDto[]> {
    const rows = await this.subscriberRepo.find({
      where: {
        trackingLinkId,
        isInternalData2: false,
        ...buildTimestampFilter(filter),
      },
      order: { id: 'ASC' },
    });
    return rows.map(toSubscriptionDto);
  }

  async findLinkSummary(trackingLinkId: number): Promise<TrackingLinkDto> {
    const [rows, count] = await this.subscriberRepo.findAndCount({
      where: { trackingLinkId, isInternalData2: false },
      order: { id: 'ASC' },
    });
    if (count === 0) {
      throw new NotFoundException(
        `No results found for tracking link "${trackingLinkId}"`,
      );
    }
    return {
      trackingLinkId,
      trackingLinkName: rows[0].trackingLinkName,
      riskLevel: rows[0].riskLevel,
      count,
    };
  }
}

function toSubscriptionDto(
  s: TrackingLinkSubscriber,
): TrackingLinkSubscriptionDto {
  return {
    trackingLinkId: s.trackingLinkId,
    trackingLinkName: s.trackingLinkName,
    username: s.username,
    userId: s.userId,
    subscriptionDate: s.subscriptionDate,
    riskLevel: s.riskLevel,
    createdAt: s.createdAt,
    updatedAt: s.updatedAt,
  };
}

function buildTimestampFilter(filter: SubscriberFilter) {
  const where: {
    createdAt?: ReturnType<typeof MoreThanOrEqual<Date>>;
    updatedAt?: ReturnType<typeof MoreThanOrEqual<Date>>;
    riskLevel?: ReturnType<typeof In<RiskLevel>>;
  } = {};
  if (filter.createdSince) {
    where.createdAt = MoreThanOrEqual(new Date(filter.createdSince));
  }
  if (filter.updatedSince) {
    where.updatedAt = MoreThanOrEqual(new Date(filter.updatedSince));
  }
  if (filter.riskLevel?.length) {
    where.riskLevel = In(filter.riskLevel);
  }
  return where;
}
