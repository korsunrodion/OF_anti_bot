import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import {
  RiskLevel,
  TrackingLinkSubscriber,
} from '../entities/tracking-link-subscriber.entity';
import { SubscriberDto } from '../dto/subscriber.dto';
import { ICategorizationService } from './categorization.service.interface';

interface Coefficients {
  wId: number;
  wTime: number;
  intercept: number;
}

// score = wId * min_id_diff + wTime * min_time_diff_sec + intercept
// Negative weights: smaller diffs (closer neighbors) yield a higher score → higher risk.
// Intercept acts as the threshold; score > 0 triggers that risk level.
// These are placeholder values — calibrate against labelled data.
const COEFFICIENTS: Record<string, Coefficients> = {
  extreme: { wId: -0.005, wTime: -0.008, intercept: 5.0 },
  veryHigh: { wId: -0.002, wTime: -0.004, intercept: 3.0 },
  high: { wId: -0.001, wTime: -0.002, intercept: 2.0 },
  low: { wId: -0.0005, wTime: -0.001, intercept: 1.0 },
};

const RISK_ORDER: RiskLevel[] = [
  'no risk',
  'low',
  'high',
  'very high',
  'extreme',
];

@Injectable()
export class CategorizationService implements ICategorizationService {
  constructor(
    @InjectRepository(TrackingLinkSubscriber)
    private readonly subscriberRepo: Repository<TrackingLinkSubscriber>,
  ) {}

  async scoreSubscriber(
    subscriber: SubscriberDto,
    trackingLinkId: string,
  ): Promise<RiskLevel> {
    const subDate = new Date(subscriber.subscriptionDate);
    const windowStart = new Date(
      subDate.getTime() - 24 * 3600 * 1000,
    ).toISOString();
    const windowEnd = new Date(
      subDate.getTime() + 24 * 3600 * 1000,
    ).toISOString();

    const neighbors = await this.subscriberRepo
      .createQueryBuilder('s')
      .where('s.trackingLinkId = :trackingLinkId', { trackingLinkId })
      .andWhere('s.userId != :userId', { userId: subscriber.userId })
      .andWhere('s.subscriptionDate BETWEEN :start AND :end', {
        start: windowStart,
        end: windowEnd,
      })
      .getMany();

    const features = this.extractFeatures(subscriber, neighbors);

    if (this.linearScore(features, COEFFICIENTS.extreme) > 0) return 'extreme';
    if (this.linearScore(features, COEFFICIENTS.veryHigh) > 0)
      return 'very high';
    if (this.linearScore(features, COEFFICIENTS.high) > 0) return 'high';
    if (this.linearScore(features, COEFFICIENTS.low) > 0) return 'low';
    return 'no risk';
  }

  aggregateRisk(scores: RiskLevel[]): RiskLevel {
    return scores.reduce<RiskLevel>(
      (max, s) => (RISK_ORDER.indexOf(s) > RISK_ORDER.indexOf(max) ? s : max),
      'no risk',
    );
  }

  private extractFeatures(
    subscriber: SubscriberDto,
    neighbors: TrackingLinkSubscriber[],
  ): { minIdDiff: number; minTimeDiffSec: number } {
    if (neighbors.length === 0) {
      return { minIdDiff: Infinity, minTimeDiffSec: Infinity };
    }

    const subTime = new Date(subscriber.subscriptionDate).getTime();

    const minIdDiff = Math.min(
      ...neighbors.map((n) => Math.abs(subscriber.userId - n.userId)),
    );
    const minTimeDiffSec = Math.min(
      ...neighbors.map(
        (n) =>
          Math.abs(subTime - new Date(n.subscriptionDate).getTime()) / 1000,
      ),
    );

    return { minIdDiff, minTimeDiffSec };
  }

  private linearScore(
    features: { minIdDiff: number; minTimeDiffSec: number },
    coeffs: Coefficients,
  ): number {
    return (
      coeffs.wId * features.minIdDiff +
      coeffs.wTime * features.minTimeDiffSec +
      coeffs.intercept
    );
  }
}
